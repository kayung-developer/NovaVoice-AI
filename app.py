import customtkinter as ctk
from tkinter import filedialog, messagebox, ttk, Scrollbar, Canvas, Frame as tkFrame, Label as tkLabel, \
    Button as tkButton
import threading
import time
import sqlite3
import hashlib
import json
import os
import uuid
from PIL import Image, ImageTk

# --- FastAPI & Related Imports ---
from fastapi import FastAPI, HTTPException, Depends, Body, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from pydantic import BaseModel, EmailStr
from typing import List, Optional, Dict

# --- TTS Engine ---
import pyttsx3

# --- Audio Playback ---
from playsound import \
    playsound  # Ensure playsound is installed: pip install playsound==1.2.2 (version 1.2.2 for compatibility)

# --- Global Configuration ---
APP_NAME = "NovaVoice AI"
APP_VERSION = "1.0.0 Ultimate"
API_HOST = "127.0.0.1"
API_PORT = 8008
API_BASE_URL = f"http://{API_HOST}:{API_PORT}"
DB_NAME = "novavoice_ai.db"
GENERATED_AUDIO_DIR = "generated_audio"
CLONED_VOICE_SAMPLES_DIR = "cloned_voice_samples"

# Ensure directories exist
os.makedirs(GENERATED_AUDIO_DIR, exist_ok=True)
os.makedirs(CLONED_VOICE_SAMPLES_DIR, exist_ok=True)

# --- Theme and Styling ---
ctk.set_appearance_mode("dark")  # Modes: "system" (default), "dark", "light"
ctk.set_default_color_theme("blue")  # Themes: "blue" (default), "green", "dark-blue"

PRIMARY_COLOR = "#1E1E2D"  # Dark purple/blue
SECONDARY_COLOR = "#2D2D44"  # Slightly lighter
ACCENT_COLOR = "#FF6B6B"  # Coral red for accents
TEXT_COLOR = "#E0E0E0"
BUTTON_HOVER_COLOR = "#FF8787"


# --- Database Setup ---
def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Users table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        subscription_tier TEXT DEFAULT 'Basic', -- Basic, Premium, Ultimate
        subscription_expiry DATE,
        api_key TEXT UNIQUE,
        daily_generations_left INTEGER DEFAULT 10
    )
    ''')

    # Voices table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS voices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, -- NULL for global/pre-set voices
        voice_name TEXT NOT NULL,
        voice_type TEXT NOT NULL, -- 'preset', 'cloned', 'designed'
        voice_params TEXT, -- JSON string for TTS engine specific params or simulated properties
        language TEXT DEFAULT 'en-US',
        accent TEXT DEFAULT 'default',
        emotion_support TEXT, -- JSON array of supported emotions
        sample_path TEXT, -- Path to sample audio for cloned voices
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    ''')

    # Add default voices if not present
    cursor.execute("SELECT COUNT(*) FROM voices WHERE voice_type = 'preset'")
    if cursor.fetchone()[0] == 0:
        default_voices = [
            ("Nova (Neutral Male)", "preset", json.dumps({"tts_engine_voice_id": 0}), "en-US", "default",
             json.dumps(["neutral", "happy", "sad"])),
            ("Stella (Neutral Female)", "preset", json.dumps({"tts_engine_voice_id": 1}), "en-US", "default",
             json.dumps(["neutral", "happy", "sad"])),
            ("Orion (Deep Male)", "preset", json.dumps({"tts_engine_voice_id": 0, "pitch_modifier": -5}), "en-US",
             "default", json.dumps(["neutral", "serious"])),
            ("Lyra (Bright Female)", "preset", json.dumps({"tts_engine_voice_id": 1, "pitch_modifier": 5}), "en-US",
             "default", json.dumps(["neutral", "excited"])),
            ("Echo (Multilingual Placeholder)", "preset", json.dumps({"tts_engine_voice_id": 0}), "mul", "various",
             json.dumps(["neutral"])),  # Placeholder for multilingual
        ]
        cursor.executemany(
            "INSERT INTO voices (voice_name, voice_type, voice_params, language, accent, emotion_support) VALUES (?, ?, ?, ?, ?, ?)",
            default_voices)

    # Generated Audio History
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS audio_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        text_input TEXT NOT NULL,
        voice_id INTEGER NOT NULL,
        generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        audio_file_path TEXT NOT NULL,
        settings TEXT, -- JSON of settings like speed, pitch, emotion
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (voice_id) REFERENCES voices (id)
    )
    ''')

    # Payments (Simulated)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        tier TEXT NOT NULL,
        amount REAL NOT NULL,
        payment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        payment_method TEXT, -- e.g., "Simulated Visa **** 1234"
        transaction_id TEXT UNIQUE,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    ''')

    conn.commit()
    conn.close()


init_db()  # Initialize database on script start


# --- Helper Functions ---
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(stored_password_hash, provided_password):
    return stored_password_hash == hashlib.sha256(provided_password.encode()).hexdigest()


def generate_api_key():
    return str(uuid.uuid4())


# --- TTS Engine (pyttsx3 based) ---
tts_engine = pyttsx3.init()


def get_pyttsx3_voices():
    voices = tts_engine.getProperty('voices')
    return [{"id": v.id, "name": v.name, "lang": v.languages, "gender": v.gender} for v in voices]


# Example: tts_engine.setProperty('voice', voices[0].id) for male, voices[1].id for female (depends on OS)

# --- FastAPI Backend ---
app_fastapi = FastAPI(title=APP_NAME, version=APP_VERSION)

app_fastapi.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all for local dev; restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Pydantic Models ---
class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    email: EmailStr
    subscription_tier: str
    api_key: Optional[str]
    daily_generations_left: int


class VoiceResponse(BaseModel):
    id: int
    voice_name: str
    voice_type: str  # 'preset', 'cloned', 'designed'
    language: str
    accent: str
    emotion_support: List[str]
    user_id: Optional[int] = None
    sample_path: Optional[str] = None


class TTSRequest(BaseModel):
    text: str
    voice_id: int
    user_api_key: str  # For API-based usage, or internal user tracking
    speed: Optional[float] = 1.0  # 0.5 to 2.0
    pitch: Optional[float] = 1.0  # Not directly supported by pyttsx3, simulated
    emotion: Optional[str] = "neutral"  # happy, sad, angry, excited


class SubscriptionRequest(BaseModel):
    user_id: int  # Or use API key / token for auth
    tier: str  # Basic, Premium, Ultimate
    payment_details: Dict  # Simulated: {"card_number": "xxxx", "expiry": "MM/YY", "cvv": "xxx"}


class ClonedVoiceCreate(BaseModel):
    voice_name: str
    user_api_key: str


# --- FastAPI Authentication (Simulated - In real app, use JWT tokens) ---
# For simplicity, we'll pass user_id or api_key. A real app needs robust auth.
def get_current_user_by_api_key(api_key: str):
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE api_key = ?", (api_key,)).fetchone()
    conn.close()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API Key")

    # Check subscription and generation limits
    if user['subscription_tier'] == 'Basic' and user['daily_generations_left'] <= 0:
        raise HTTPException(status_code=403, detail="Daily generation limit reached for Basic tier.")

    return user


# --- FastAPI Endpoints ---
@app_fastapi.post("/register", response_model=UserResponse)
async def register_user(user_data: UserCreate):
    conn = get_db_connection()
    try:
        api_key = generate_api_key()
        hashed_pass = hash_password(user_data.password)
        cursor = conn.execute(
            "INSERT INTO users (username, email, password_hash, api_key, subscription_tier, daily_generations_left) VALUES (?, ?, ?, ?, ?, ?)",
            (user_data.username, user_data.email, hashed_pass, api_key, 'Basic', 10)  # Default to Basic, 10 generations
        )
        conn.commit()
        user_id = cursor.lastrowid
        new_user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return UserResponse(**dict(new_user))
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Username or email already exists")
    finally:
        conn.close()


@app_fastapi.post("/login", response_model=UserResponse)
async def login_user(user_data: UserLogin):
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (user_data.email,)).fetchone()
    conn.close()
    if not user or not verify_password(user['password_hash'], user_data.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return UserResponse(**dict(user))


@app_fastapi.get("/voices", response_model=List[VoiceResponse])
async def list_voices(user_api_key: Optional[str] = None):  # User can see their voices + preset
    conn = get_db_connection()
    user_id = None
    if user_api_key:
        user = conn.execute("SELECT id FROM users WHERE api_key = ?", (user_api_key,)).fetchone()
        if user:
            user_id = user['id']

    query = "SELECT * FROM voices WHERE voice_type = 'preset'"
    params = []
    if user_id:
        query += " OR (user_id = ? AND voice_type IN ('cloned', 'designed'))"
        params.append(user_id)

    voices_db = conn.execute(query, tuple(params)).fetchall()
    conn.close()

    response_voices = []
    for v_row in voices_db:
        v = dict(v_row)
        v['emotion_support'] = json.loads(v['emotion_support']) if v['emotion_support'] else []
        response_voices.append(VoiceResponse(**v))
    return response_voices


@app_fastapi.post("/tts/generate")
async def generate_speech(request_data: TTSRequest):
    user = get_current_user_by_api_key(request_data.user_api_key)  # Authenticate and check limits

    conn = get_db_connection()
    voice_info = conn.execute("SELECT * FROM voices WHERE id = ?", (request_data.voice_id,)).fetchone()
    if not voice_info:
        conn.close()
        raise HTTPException(status_code=404, detail="Voice not found")

    # Update generation count
    if user['subscription_tier'] == 'Basic':
        conn.execute("UPDATE users SET daily_generations_left = daily_generations_left - 1 WHERE id = ?", (user['id'],))
        conn.commit()

    conn.close()

    try:
        # --- pyttsx3 specific generation ---
        voice_params = json.loads(voice_info['voice_params']) if voice_info['voice_params'] else {}

        # Select pyttsx3 voice (this logic is basic, a real system would be more complex)
        py_voices = tts_engine.getProperty('voices')
        selected_py_voice_id = voice_params.get('tts_engine_voice_id', 0)  # Default to first voice
        if selected_py_voice_id < len(py_voices):
            tts_engine.setProperty('voice', py_voices[selected_py_voice_id].id)
        else:  # Fallback if ID is out of range
            tts_engine.setProperty('voice', py_voices[0].id)

        # Apply settings (pyttsx3 has limited direct control over pitch/emotion)
        rate = tts_engine.getProperty('rate')
        tts_engine.setProperty('rate', rate * request_data.speed)  # Adjust speed relative to current

        # Emotion simulation (very basic)
        text_to_speak = request_data.text
        if request_data.emotion == "happy":
            text_to_speak = "Yay! " + text_to_speak
            # Could try to slightly increase pitch if pyttsx3 had fine control
        elif request_data.emotion == "sad":
            text_to_speak = "Alas... " + text_to_speak
            # Could try to slightly decrease pitch/rate

        # Pitch simulation (pyttsx3 doesn't have a direct pitch control like some engines)
        # If voice_params contains a pitch_modifier, it's for show or if a future engine is used
        # We can log that it was requested:
        print(f"Requested pitch factor: {request_data.pitch}")

        filename = f"{uuid.uuid4()}.wav"  # .mp3 for gTTS, .wav for pyttsx3
        filepath = os.path.join(GENERATED_AUDIO_DIR, filename)

        tts_engine.save_to_file(text_to_speak, filepath)
        tts_engine.runAndWait()

        # Reset rate for next generation
        tts_engine.setProperty('rate', rate)

        # Log to history
        conn = get_db_connection()
        settings_json = json.dumps({
            "speed": request_data.speed,
            "pitch": request_data.pitch,
            "emotion": request_data.emotion
        })
        conn.execute(
            "INSERT INTO audio_history (user_id, text_input, voice_id, audio_file_path, settings) VALUES (?, ?, ?, ?, ?)",
            (user['id'], request_data.text, request_data.voice_id, filepath, settings_json)
        )
        conn.commit()
        conn.close()

        return FileResponse(filepath, media_type="audio/wav", filename=filename)

    except Exception as e:
        print(f"TTS generation error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate speech: {str(e)}")


@app_fastapi.post("/voice/clone", response_model=VoiceResponse)
async def clone_voice(
        user_api_key: str = Body(...),
        voice_name: str = Body(...),
        language: str = Body("en-US"),  # Add language and accent if needed
        accent: str = Body("default"),
        voice_sample: UploadFile = File(...)
):
    user = get_current_user_by_api_key(user_api_key)
    if user['subscription_tier'] not in ['Premium', 'Ultimate']:
        raise HTTPException(status_code=403, detail="Voice cloning requires Premium or Ultimate tier.")

    # Simulate cloning: Save the sample file and create a voice entry
    # In a real system, this would involve complex ML processing.
    sample_filename = f"clone_{user['id']}_{uuid.uuid4()}_{voice_sample.filename}"
    sample_filepath = os.path.join(CLONED_VOICE_SAMPLES_DIR, sample_filename)

    with open(sample_filepath, "wb") as buffer:
        buffer.write(await voice_sample.read())

    # Simulated parameters: use a default pyttsx3 voice but mark as 'cloned'
    # A real system would store actual model parameters.
    # Here, we might pick a different pyttsx3 voice ID to make it sound distinct, or just log it.
    cloned_voice_params = json.dumps({"tts_engine_voice_id": len(get_pyttsx3_voices()) % 2,
                                      "cloned_from_sample": sample_filename})  # Cycle between 0 and 1

    conn = get_db_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO voices (user_id, voice_name, voice_type, voice_params, language, accent, emotion_support, sample_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user['id'], voice_name, 'cloned', cloned_voice_params, language, accent, json.dumps(["neutral"]),
             sample_filepath)
        )
        conn.commit()
        voice_id = cursor.lastrowid
        new_voice_db = conn.execute("SELECT * FROM voices WHERE id = ?", (voice_id,)).fetchone()

        response_voice = dict(new_voice_db)
        response_voice['emotion_support'] = json.loads(response_voice['emotion_support']) if response_voice[
            'emotion_support'] else []
        return VoiceResponse(**response_voice)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save cloned voice: {str(e)}")
    finally:
        conn.close()


@app_fastapi.post("/subscribe")
async def handle_subscription(request_data: SubscriptionRequest):
    # This is highly simulated. A real system needs a payment gateway.
    user_id = request_data.user_id  # In real app, get from authenticated token
    tier = request_data.tier

    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")

    # Simulate payment processing
    print(f"Simulating payment for user {user_id}, tier {tier} with details: {request_data.payment_details}")
    time.sleep(1)  # Simulate network latency

    # Update user's subscription
    # For simplicity, new subscription lasts 30 days from now.
    from datetime import date, timedelta
    expiry_date = (date.today() + timedelta(days=30)).isoformat()

    generations_map = {"Basic": 10, "Premium": 100, "Ultimate": 1000}  # Daily generations

    conn.execute(
        "UPDATE users SET subscription_tier = ?, subscription_expiry = ?, daily_generations_left = ? WHERE id = ?",
        (tier, expiry_date, generations_map.get(tier, 10), user_id)
    )
    # Log simulated payment
    conn.execute(
        "INSERT INTO payments (user_id, tier, amount, payment_method, transaction_id) VALUES (?, ?, ?, ?, ?)",
        (user_id, tier, {"Basic": 0.0, "Premium": 9.99, "Ultimate": 29.99}.get(tier, 0),  # Simulated prices
         f"Simulated Card **** {request_data.payment_details.get('card_number', '0000')[-4:]}",
         f"SIM_TXN_{uuid.uuid4()}")
    )
    conn.commit()
    updated_user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()

    return {"message": f"Subscription to {tier} successful!", "user": UserResponse(**dict(updated_user))}


@app_fastapi.get("/user/history/{user_api_key}")
async def get_user_history(user_api_key: str):
    user = get_current_user_by_api_key(user_api_key)
    conn = get_db_connection()
    history_db = conn.execute(
        """
        SELECT ah.id, ah.text_input, v.voice_name, ah.generated_at, ah.audio_file_path, ah.settings
        FROM audio_history ah
        JOIN voices v ON ah.voice_id = v.id
        WHERE ah.user_id = ?
        ORDER BY ah.generated_at DESC
        """, (user['id'],)
    ).fetchall()
    conn.close()
    return [dict(row) for row in history_db]


# --- FastAPI Server Thread ---
def run_fastapi_server():
    uvicorn.run(app_fastapi, host=API_HOST, port=API_PORT, log_level="info")


# --- CustomTkinter Frontend ---
class NovaVoiceApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(APP_NAME)
        self.geometry("1200x780")
        self.configure(fg_color=PRIMARY_COLOR)

        self.current_user = None  # Store logged-in user details (dict)
        self.available_voices = []  # Store voice list from backend
        self.current_audio_filepath = None  # Path to the last generated audio

        # Load icons (placeholders for now, real app would load images)
        # self.icon_synth = self_load_icon("synth.png") # Example

        self.init_login_screen()
        # self.init_main_ui() # This will be called after successful login

    def init_login_screen(self):
        if hasattr(self, 'main_frame') and self.main_frame:
            self.main_frame.destroy()

        self.login_frame = ctk.CTkFrame(self, fg_color=PRIMARY_COLOR)
        self.login_frame.pack(fill="both", expand=True)

        center_frame = ctk.CTkFrame(self.login_frame, fg_color=SECONDARY_COLOR, corner_radius=15)
        center_frame.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.4, relheight=0.6)

        ctk.CTkLabel(center_frame, text=APP_NAME, font=ctk.CTkFont(size=36, weight="bold"),
                     text_color=ACCENT_COLOR).pack(pady=(30, 10))
        ctk.CTkLabel(center_frame, text="Ultimate AI Voice Generation", font=ctk.CTkFont(size=16),
                     text_color=TEXT_COLOR).pack(pady=(0, 30))

        self.email_entry = ctk.CTkEntry(center_frame, placeholder_text="Email", width=300, height=40,
                                        font=ctk.CTkFont(size=14))
        self.email_entry.pack(pady=10)

        self.password_entry = ctk.CTkEntry(center_frame, placeholder_text="Password", show="*", width=300, height=40,
                                           font=ctk.CTkFont(size=14))
        self.password_entry.pack(pady=10)

        login_button = ctk.CTkButton(center_frame, text="Login", command=self.handle_login, width=150, height=40,
                                     fg_color=ACCENT_COLOR, hover_color=BUTTON_HOVER_COLOR, font=ctk.CTkFont(size=16))
        login_button.pack(pady=20)

        self.show_register_button = ctk.CTkButton(center_frame, text="Don't have an account? Register",
                                                  command=self.show_register_screen, fg_color="transparent",
                                                  text_color=ACCENT_COLOR, hover=False, font=ctk.CTkFont(size=12))
        self.show_register_button.pack(pady=5)

        self.status_label_login = ctk.CTkLabel(center_frame, text="", font=ctk.CTkFont(size=12))
        self.status_label_login.pack(pady=10)

    def show_register_screen(self):
        self.login_frame.destroy()  # Clear login frame
        self.register_frame = ctk.CTkFrame(self, fg_color=PRIMARY_COLOR)
        self.register_frame.pack(fill="both", expand=True)

        center_frame = ctk.CTkFrame(self.register_frame, fg_color=SECONDARY_COLOR, corner_radius=15)
        center_frame.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.4, relheight=0.7)

        ctk.CTkLabel(center_frame, text="Create Account", font=ctk.CTkFont(size=28, weight="bold"),
                     text_color=ACCENT_COLOR).pack(pady=(30, 20))

        self.reg_username_entry = ctk.CTkEntry(center_frame, placeholder_text="Username", width=300, height=40,
                                               font=ctk.CTkFont(size=14))
        self.reg_username_entry.pack(pady=10)
        self.reg_email_entry = ctk.CTkEntry(center_frame, placeholder_text="Email", width=300, height=40,
                                            font=ctk.CTkFont(size=14))
        self.reg_email_entry.pack(pady=10)
        self.reg_password_entry = ctk.CTkEntry(center_frame, placeholder_text="Password", show="*", width=300,
                                               height=40, font=ctk.CTkFont(size=14))
        self.reg_password_entry.pack(pady=10)
        self.reg_confirm_password_entry = ctk.CTkEntry(center_frame, placeholder_text="Confirm Password", show="*",
                                                       width=300, height=40, font=ctk.CTkFont(size=14))
        self.reg_confirm_password_entry.pack(pady=10)

        register_button = ctk.CTkButton(center_frame, text="Register", command=self.handle_register, width=150,
                                        height=40,
                                        fg_color=ACCENT_COLOR, hover_color=BUTTON_HOVER_COLOR,
                                        font=ctk.CTkFont(size=16))
        register_button.pack(pady=20)

        self.show_login_button = ctk.CTkButton(center_frame, text="Already have an account? Login",
                                               command=self.handle_show_login_from_register, fg_color="transparent",
                                               text_color=ACCENT_COLOR, hover=False, font=ctk.CTkFont(size=12))
        self.show_login_button.pack(pady=5)

        self.status_label_register = ctk.CTkLabel(center_frame, text="", font=ctk.CTkFont(size=12))
        self.status_label_register.pack(pady=10)

    def handle_show_login_from_register(self):
        if hasattr(self, 'register_frame'):
            self.register_frame.destroy()
        self.init_login_screen()

    def handle_login(self):
        email = self.email_entry.get()
        password = self.password_entry.get()
        if not email or not password:
            self.status_label_login.configure(text="Email and password are required.", text_color="orange")
            return

        try:
            import requests  # Import here as it's used by frontend
            response = requests.post(f"{API_BASE_URL}/login", json={"email": email, "password": password})
            if response.status_code == 200:
                self.current_user = response.json()
                self.status_label_login.configure(text="Login successful!", text_color="green")
                self.after(1000, self.init_main_ui)  # Delay to show message
            else:
                error_detail = response.json().get("detail", "Login failed.")
                self.status_label_login.configure(text=error_detail, text_color="red")
        except requests.exceptions.RequestException as e:
            self.status_label_login.configure(text=f"Connection error: {e}", text_color="red")
            messagebox.showerror("Connection Error", "Could not connect to the backend server. Is it running?")

    def handle_register(self):
        username = self.reg_username_entry.get()
        email = self.reg_email_entry.get()
        password = self.reg_password_entry.get()
        confirm_password = self.reg_confirm_password_entry.get()

        if not all([username, email, password, confirm_password]):
            self.status_label_register.configure(text="All fields are required.", text_color="orange")
            return
        if password != confirm_password:
            self.status_label_register.configure(text="Passwords do not match.", text_color="orange")
            return

        try:
            import requests
            response = requests.post(f"{API_BASE_URL}/register",
                                     json={"username": username, "email": email, "password": password})
            if response.status_code == 200:
                self.status_label_register.configure(text="Registration successful! Please login.", text_color="green")
                self.current_user = response.json()  # auto-login or prompt
                self.after(1500, self.handle_show_login_from_register)  # Go to login screen
            else:
                error_detail = response.json().get("detail", "Registration failed.")
                self.status_label_register.configure(text=error_detail, text_color="red")
        except requests.exceptions.RequestException as e:
            self.status_label_register.configure(text=f"Connection error: {e}", text_color="red")
            messagebox.showerror("Connection Error", "Could not connect to the backend server.")

    def init_main_ui(self):
        if hasattr(self, 'login_frame') and self.login_frame:
            self.login_frame.destroy()
        if hasattr(self, 'register_frame') and self.register_frame:
            self.register_frame.destroy()

        self.main_frame = ctk.CTkFrame(self, fg_color=PRIMARY_COLOR)
        self.main_frame.pack(fill="both", expand=True)

        self.main_frame.grid_columnconfigure(1, weight=1)
        self.main_frame.grid_rowconfigure(0, weight=1)

        # --- Sidebar ---
        self.sidebar_frame = ctk.CTkFrame(self.main_frame, width=250, corner_radius=0, fg_color=SECONDARY_COLOR)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsw")
        self.sidebar_frame.grid_rowconfigure(6, weight=1)  # Push logout to bottom

        logo_label = ctk.CTkLabel(self.sidebar_frame, text=APP_NAME, font=ctk.CTkFont(size=24, weight="bold"),
                                  text_color=ACCENT_COLOR)
        logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        user_info_text = f"{self.current_user['username']} ({self.current_user['subscription_tier']})"
        self.user_info_label = ctk.CTkLabel(self.sidebar_frame, text=user_info_text, font=ctk.CTkFont(size=12))
        self.user_info_label.grid(row=1, column=0, padx=20, pady=(0, 20))

        self.nav_buttons = {}
        nav_items = {
            "Speech Synthesis": self.show_speech_synthesis_frame,
            "Voice Lab": self.show_voice_lab_frame,
            "History": self.show_history_frame,
            "Subscription": self.show_subscription_frame,
            # "Settings": self.show_settings_frame # Future
        }

        for i, (text, command) in enumerate(nav_items.items()):
            button = ctk.CTkButton(self.sidebar_frame, text=text, command=command,
                                   fg_color="transparent", text_color=TEXT_COLOR,
                                   hover_color=PRIMARY_COLOR, anchor="w",
                                   font=ctk.CTkFont(size=16))
            button.grid(row=i + 2, column=0, sticky="ew", padx=10, pady=5)
            self.nav_buttons[text] = button

        logout_button = ctk.CTkButton(self.sidebar_frame, text="Logout", command=self.handle_logout,
                                      fg_color=ACCENT_COLOR, hover_color=BUTTON_HOVER_COLOR,
                                      font=ctk.CTkFont(size=16))
        logout_button.grid(row=len(nav_items) + 3, column=0, sticky="sew", padx=20, pady=20)

        # --- Content Area ---
        self.content_frame = ctk.CTkFrame(self.main_frame, corner_radius=10, fg_color=PRIMARY_COLOR)
        self.content_frame.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)

        self.load_voices()  # Load available voices for the user
        self.show_speech_synthesis_frame()  # Default view

    def handle_logout(self):
        self.current_user = None
        self.main_frame.destroy()
        self.init_login_screen()

    def update_user_info_display(self):
        if self.current_user and hasattr(self, 'user_info_label'):
            conn = get_db_connection()
            user_db = conn.execute("SELECT subscription_tier, daily_generations_left FROM users WHERE id = ?",
                                   (self.current_user['id'],)).fetchone()
            conn.close()
            if user_db:
                self.current_user['subscription_tier'] = user_db['subscription_tier']
                self.current_user['daily_generations_left'] = user_db['daily_generations_left']

            user_info_text = f"{self.current_user['username']} ({self.current_user['subscription_tier']})"
            if self.current_user['subscription_tier'] == 'Basic':
                user_info_text += f" - Gens left: {self.current_user['daily_generations_left']}"
            self.user_info_label.configure(text=user_info_text)

    def clear_content_frame(self):
        for widget in self.content_frame.winfo_children():
            widget.destroy()
        # Reset active button state
        for btn in self.nav_buttons.values():
            btn.configure(fg_color="transparent")

    def set_active_nav_button(self, button_text):
        if button_text in self.nav_buttons:
            self.nav_buttons[button_text].configure(fg_color=PRIMARY_COLOR)  # Highlight active

    def load_voices(self):
        if not self.current_user: return
        try:
            import requests
            params = {}
            if self.current_user and 'api_key' in self.current_user:
                params['user_api_key'] = self.current_user['api_key']

            response = requests.get(f"{API_BASE_URL}/voices", params=params)
            if response.status_code == 200:
                self.available_voices = response.json()
                # print(f"Loaded voices: {self.available_voices}")
            else:
                messagebox.showerror("Error", f"Failed to load voices: {response.json().get('detail')}")
                self.available_voices = []
        except requests.exceptions.RequestException as e:
            messagebox.showerror("Connection Error", f"Could not load voices: {e}")
            self.available_voices = []

    def show_speech_synthesis_frame(self):
        self.clear_content_frame()
        self.set_active_nav_button("Speech Synthesis")
        self.update_user_info_display()

        ctk.CTkLabel(self.content_frame, text="Speech Synthesis", font=ctk.CTkFont(size=28, weight="bold")).pack(
            pady=(10, 20), anchor="w", padx=20)

        # Main layout: Left for inputs, Right for settings/output
        tts_main_panel = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        tts_main_panel.pack(fill="both", expand=True, padx=20, pady=10)
        tts_main_panel.grid_columnconfigure(0, weight=2)  # Text input area
        tts_main_panel.grid_columnconfigure(1, weight=1)  # Settings area

        # Left Panel: Text Input
        text_input_frame = ctk.CTkFrame(tts_main_panel, fg_color=SECONDARY_COLOR, corner_radius=10)
        text_input_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        text_input_frame.grid_rowconfigure(0, weight=1)
        text_input_frame.grid_columnconfigure(0, weight=1)

        self.text_to_speak_entry = ctk.CTkTextbox(text_input_frame, height=300, font=ctk.CTkFont(size=16), wrap="word",
                                                  border_width=2, border_color=ACCENT_COLOR, activate_scrollbars=True)
        self.text_to_speak_entry.grid(row=0, column=0, sticky="nsew", padx=15, pady=15)
        self.text_to_speak_entry.insert("0.0",
                                        "Hello, welcome to NovaVoice AI. Type your text here to generate speech.")

        # Character count (Example of a small utility)
        # self.char_count_label = ctk.CTkLabel(text_input_frame, text="Characters: 0 / 5000", font=ctk.CTkFont(size=10))
        # self.char_count_label.grid(row=1, column=0, sticky="e", padx=15, pady=(0,10))
        # def update_char_count(event=None):
        #    count = len(self.text_to_speak_entry.get("1.0", "end-1c"))
        #    self.char_count_label.configure(text=f"Characters: {count} / 5000") # Max limit based on tier
        # self.text_to_speak_entry.bind("<KeyRelease>", update_char_count)
        # update_char_count()

        # Right Panel: Settings & Generation
        settings_frame = ctk.CTkFrame(tts_main_panel, fg_color=SECONDARY_COLOR, corner_radius=10)
        settings_frame.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        settings_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(settings_frame, text="Voice Settings", font=ctk.CTkFont(size=18, weight="bold")).grid(row=0,
                                                                                                           column=0,
                                                                                                           columnspan=2,
                                                                                                           pady=(
                                                                                                           15, 10),
                                                                                                           padx=15,
                                                                                                           sticky="w")

        # Voice Selection
        ctk.CTkLabel(settings_frame, text="Select Voice:", font=ctk.CTkFont(size=14)).grid(row=1, column=0, padx=15,
                                                                                           pady=5, sticky="w")
        voice_names = [v['voice_name'] for v in self.available_voices] if self.available_voices else [
            "No voices available"]
        self.voice_dropdown = ctk.CTkComboBox(settings_frame, values=voice_names, width=250, height=35,
                                              font=ctk.CTkFont(size=14), dropdown_font=ctk.CTkFont(size=14))
        if voice_names: self.voice_dropdown.set(voice_names[0])
        self.voice_dropdown.grid(row=2, column=0, columnspan=2, padx=15, pady=5, sticky="ew")

        # Speed
        ctk.CTkLabel(settings_frame, text="Speed:", font=ctk.CTkFont(size=14)).grid(row=3, column=0, padx=15, pady=5,
                                                                                    sticky="w")
        self.speed_slider = ctk.CTkSlider(settings_frame, from_=0.5, to=2.0, number_of_steps=15)
        self.speed_slider.set(1.0)
        self.speed_slider.grid(row=4, column=0, columnspan=2, padx=15, pady=5, sticky="ew")

        # Pitch (Simulated for pyttsx3 - UI only)
        ctk.CTkLabel(settings_frame, text="Pitch (Simulated):", font=ctk.CTkFont(size=14)).grid(row=5, column=0,
                                                                                                padx=15, pady=5,
                                                                                                sticky="w")
        self.pitch_slider = ctk.CTkSlider(settings_frame, from_=0.5, to=2.0, number_of_steps=15)
        self.pitch_slider.set(1.0)
        self.pitch_slider.grid(row=6, column=0, columnspan=2, padx=15, pady=5, sticky="ew")

        # Emotion (Simulated)
        ctk.CTkLabel(settings_frame, text="Emotion (Simulated):", font=ctk.CTkFont(size=14)).grid(row=7, column=0,
                                                                                                  padx=15, pady=5,
                                                                                                  sticky="w")
        emotions = ["neutral", "happy", "sad", "excited", "angry", "serious"]  # Example emotions
        self.emotion_dropdown = ctk.CTkComboBox(settings_frame, values=emotions, width=250, height=35,
                                                font=ctk.CTkFont(size=14), dropdown_font=ctk.CTkFont(size=14))
        self.emotion_dropdown.set("neutral")
        self.emotion_dropdown.grid(row=8, column=0, columnspan=2, padx=15, pady=5, sticky="ew")

        # Generate Button
        self.generate_button = ctk.CTkButton(settings_frame, text="Generate Speech",
                                             command=self.handle_generate_speech,
                                             height=45, fg_color=ACCENT_COLOR, hover_color=BUTTON_HOVER_COLOR,
                                             font=ctk.CTkFont(size=18, weight="bold"))
        self.generate_button.grid(row=9, column=0, columnspan=2, padx=15, pady=(20, 10), sticky="ew")

        # Audio Player Area (Placeholder)
        self.player_frame = ctk.CTkFrame(settings_frame, fg_color="transparent", height=80)
        self.player_frame.grid(row=10, column=0, columnspan=2, padx=15, pady=10, sticky="ew")
        self.play_button = ctk.CTkButton(self.player_frame, text="▶ Play", state="disabled", command=self.play_audio,
                                         width=100)
        self.play_button.pack(side="left", padx=5)
        self.download_button = ctk.CTkButton(self.player_frame, text="⬇ Download", state="disabled",
                                             command=self.download_audio, width=100)
        self.download_button.pack(side="left", padx=5)

        self.tts_status_label = ctk.CTkLabel(settings_frame, text="", font=ctk.CTkFont(size=12))
        self.tts_status_label.grid(row=11, column=0, columnspan=2, padx=15, pady=(5, 15), sticky="ew")

    def handle_generate_speech(self):
        if not self.current_user:
            messagebox.showerror("Error", "Not logged in.")
            return

        text = self.text_to_speak_entry.get("1.0", "end-1c").strip()
        selected_voice_name = self.voice_dropdown.get()

        if not text:
            self.tts_status_label.configure(text="Please enter some text.", text_color="orange")
            return
        if not selected_voice_name or selected_voice_name == "No voices available":
            self.tts_status_label.configure(text="Please select a voice.", text_color="orange")
            return

        selected_voice_obj = next((v for v in self.available_voices if v['voice_name'] == selected_voice_name), None)
        if not selected_voice_obj:
            self.tts_status_label.configure(text="Selected voice not found in available list.", text_color="red")
            return

        payload = {
            "text": text,
            "voice_id": selected_voice_obj['id'],
            "user_api_key": self.current_user['api_key'],
            "speed": self.speed_slider.get(),
            "pitch": self.pitch_slider.get(),
            "emotion": self.emotion_dropdown.get()
        }

        self.tts_status_label.configure(text="Generating audio...", text_color=TEXT_COLOR)
        self.generate_button.configure(state="disabled", text="Generating...")
        self.play_button.configure(state="disabled")
        self.download_button.configure(state="disabled")
        self.update()  # Force UI update

        try:
            import requests
            response = requests.post(f"{API_BASE_URL}/tts/generate", json=payload, stream=True)
            if response.status_code == 200:
                self.current_audio_filepath = os.path.join(GENERATED_AUDIO_DIR, f"temp_{uuid.uuid4()}.wav")
                with open(self.current_audio_filepath, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)

                self.tts_status_label.configure(text="Audio generated successfully!", text_color="green")
                self.play_button.configure(state="normal")
                self.download_button.configure(state="normal")
                self.update_user_info_display()  # Update generation count if changed
            else:
                error_detail = response.json().get("detail", "Failed to generate speech.")
                self.tts_status_label.configure(text=error_detail, text_color="red")
                messagebox.showerror("TTS Error", error_detail)
                self.current_audio_filepath = None
        except requests.exceptions.RequestException as e:
            self.tts_status_label.configure(text=f"Connection error: {e}", text_color="red")
            messagebox.showerror("Connection Error", f"Could not connect to TTS service: {e}")
            self.current_audio_filepath = None
        finally:
            self.generate_button.configure(state="normal", text="Generate Speech")

    def play_audio(self):
        if self.current_audio_filepath and os.path.exists(self.current_audio_filepath):
            try:
                # Run playsound in a separate thread to avoid UI freeze
                threading.Thread(target=playsound, args=(self.current_audio_filepath,), daemon=True).start()
            except Exception as e:
                messagebox.showerror("Playback Error",
                                     f"Could not play audio: {e}\nEnsure you have a WAV player or library like playsound installed and working.")
        else:
            messagebox.showwarning("No Audio", "No audio file to play. Please generate speech first.")

    def download_audio(self):
        if self.current_audio_filepath and os.path.exists(self.current_audio_filepath):
            try:
                save_path = filedialog.asksaveasfilename(
                    defaultextension=".wav",
                    filetypes=[("WAV files", "*.wav"), ("All files", "*.*")],
                    initialfile="generated_speech.wav"
                )
                if save_path:
                    import shutil
                    shutil.copy(self.current_audio_filepath, save_path)
                    messagebox.showinfo("Download Complete", f"Audio saved to {save_path}")
            except Exception as e:
                messagebox.showerror("Download Error", f"Could not save audio: {e}")
        else:
            messagebox.showwarning("No Audio", "No audio file to download. Please generate speech first.")

    def show_voice_lab_frame(self):
        self.clear_content_frame()
        self.set_active_nav_button("Voice Lab")
        self.load_voices()  # Refresh voices which might include newly cloned ones

        ctk.CTkLabel(self.content_frame, text="Voice Lab (Cloning & Design - Simulated)",
                     font=ctk.CTkFont(size=28, weight="bold")).pack(pady=(10, 20), anchor="w", padx=20)

        tabview = ctk.CTkTabview(self.content_frame, fg_color=SECONDARY_COLOR,
                                 segmented_button_selected_color=ACCENT_COLOR,
                                 segmented_button_fg_color=PRIMARY_COLOR,
                                 segmented_button_unselected_color=PRIMARY_COLOR)
        tabview.pack(fill="both", expand=True, padx=20, pady=10)

        tabview.add("Clone Voice")
        tabview.add("My Voices")
        # tabview.add("Design Voice (Future)") # Placeholder for future feature

        # --- Clone Voice Tab ---
        clone_tab = tabview.tab("Clone Voice")

        ctk.CTkLabel(clone_tab, text="Clone a New Voice (Simulated)", font=ctk.CTkFont(size=20)).pack(pady=10)
        ctk.CTkLabel(clone_tab, text="Upload a short audio sample (e.g., WAV, MP3 - min 5 seconds).",
                     font=ctk.CTkFont(size=12)).pack(pady=5)
        ctk.CTkLabel(clone_tab, text="Cloning requires Premium or Ultimate subscription.",
                     font=ctk.CTkFont(size=10, weight="bold"), text_color=ACCENT_COLOR).pack(pady=(0, 10))

        self.clone_voice_name_entry = ctk.CTkEntry(clone_tab, placeholder_text="Name for your new voice", width=300)
        self.clone_voice_name_entry.pack(pady=10)

        self.clone_sample_path_label = ctk.CTkLabel(clone_tab, text="No audio sample selected.")
        self.clone_sample_path_label.pack(pady=5)

        self.selected_clone_sample_filepath = None
        upload_button = ctk.CTkButton(clone_tab, text="Upload Audio Sample", command=self.select_clone_sample)
        upload_button.pack(pady=10)

        # Language and Accent for cloned voice (optional, can default or be detected)
        # For simplicity, these are manual inputs for now
        ctk.CTkLabel(clone_tab, text="Language (e.g., en-US, es-ES):").pack(pady=(5, 0))
        self.clone_lang_entry = ctk.CTkEntry(clone_tab, placeholder_text="en-US", width=150)
        self.clone_lang_entry.insert(0, "en-US")
        self.clone_lang_entry.pack(pady=5)

        ctk.CTkLabel(clone_tab, text="Accent (e.g., default, british):").pack(pady=(5, 0))
        self.clone_accent_entry = ctk.CTkEntry(clone_tab, placeholder_text="default", width=150)
        self.clone_accent_entry.insert(0, "default")
        self.clone_accent_entry.pack(pady=5)

        self.start_clone_button = ctk.CTkButton(clone_tab, text="Start Cloning Process",
                                                command=self.handle_start_cloning,
                                                fg_color=ACCENT_COLOR, hover_color=BUTTON_HOVER_COLOR, height=40)
        self.start_clone_button.pack(pady=20)

        self.clone_status_label = ctk.CTkLabel(clone_tab, text="")
        self.clone_status_label.pack(pady=10)

        # --- My Voices Tab ---
        my_voices_tab = tabview.tab("My Voices")
        ctk.CTkLabel(my_voices_tab, text="Your Custom Voices", font=ctk.CTkFont(size=20)).pack(pady=10)

        # This should be a scrollable list or treeview
        self.my_voices_list_frame = ctk.CTkScrollableFrame(my_voices_tab, fg_color=PRIMARY_COLOR)
        self.my_voices_list_frame.pack(fill="both", expand=True, padx=10, pady=10)
        self.populate_my_voices_list()

    def select_clone_sample(self):
        filepath = filedialog.askopenfilename(
            title="Select Audio Sample",
            filetypes=(("Audio Files", "*.wav *.mp3"), ("All files", "*.*"))
        )
        if filepath:
            self.selected_clone_sample_filepath = filepath
            self.clone_sample_path_label.configure(text=os.path.basename(filepath))
        else:
            self.selected_clone_sample_filepath = None
            self.clone_sample_path_label.configure(text="No audio sample selected.")

    def handle_start_cloning(self):
        if not self.current_user: return
        voice_name = self.clone_voice_name_entry.get()
        language = self.clone_lang_entry.get() or "en-US"
        accent = self.clone_accent_entry.get() or "default"

        if not voice_name:
            self.clone_status_label.configure(text="Please enter a name for the voice.", text_color="orange")
            return
        if not self.selected_clone_sample_filepath:
            self.clone_status_label.configure(text="Please select an audio sample.", text_color="orange")
            return

        if self.current_user['subscription_tier'] not in ['Premium', 'Ultimate']:
            messagebox.showerror("Subscription Required",
                                 "Voice cloning is available for Premium and Ultimate subscribers only.")
            self.clone_status_label.configure(text="Upgrade to Premium or Ultimate for cloning.", text_color="orange")
            return

        self.clone_status_label.configure(text="Cloning voice... (This is simulated)", text_color=TEXT_COLOR)
        self.start_clone_button.configure(state="disabled", text="Cloning...")
        self.update()

        try:
            import requests
            files = {'voice_sample': (os.path.basename(self.selected_clone_sample_filepath),
                                      open(self.selected_clone_sample_filepath, 'rb'),
                                      'audio/wav')}  # Adjust MIME type if needed
            data = {
                'user_api_key': self.current_user['api_key'],
                'voice_name': voice_name,
                'language': language,
                'accent': accent
            }

            response = requests.post(f"{API_BASE_URL}/voice/clone", data=data, files=files)

            if response.status_code == 200:
                new_voice = response.json()
                self.clone_status_label.configure(text=f"Voice '{new_voice['voice_name']}' cloned successfully!",
                                                  text_color="green")
                self.load_voices()  # Refresh main voice list
                self.populate_my_voices_list()  # Refresh list in My Voices tab
                self.clone_voice_name_entry.delete(0, 'end')
                self.selected_clone_sample_filepath = None
                self.clone_sample_path_label.configure(text="No audio sample selected.")
            else:
                error_detail = response.json().get("detail", "Cloning failed.")
                self.clone_status_label.configure(text=error_detail, text_color="red")
                messagebox.showerror("Cloning Error", error_detail)
        except requests.exceptions.RequestException as e:
            self.clone_status_label.configure(text=f"Connection error: {e}", text_color="red")
            messagebox.showerror("Connection Error", f"Could not connect to cloning service: {e}")
        except Exception as e:  # Catch other file errors etc.
            self.clone_status_label.configure(text=f"Error: {e}", text_color="red")
            messagebox.showerror("Error", f"An unexpected error occurred: {e}")
        finally:
            self.start_clone_button.configure(state="normal", text="Start Cloning Process")

    def populate_my_voices_list(self):
        for widget in self.my_voices_list_frame.winfo_children():
            widget.destroy()

        if not self.current_user: return

        my_voices = [v for v in self.available_voices if v.get('user_id') == self.current_user['id']]

        if not my_voices:
            ctk.CTkLabel(self.my_voices_list_frame, text="You haven't created any custom voices yet.").pack(pady=10)
            return

        for voice in my_voices:
            voice_frame = ctk.CTkFrame(self.my_voices_list_frame, fg_color=SECONDARY_COLOR, corner_radius=5)
            voice_frame.pack(fill="x", pady=5, padx=5)

            name_label = ctk.CTkLabel(voice_frame,
                                      text=f"{voice['voice_name']} ({voice['voice_type']}) - Lang: {voice['language']}",
                                      anchor="w")
            name_label.pack(side="left", padx=10, pady=5)
            # Add delete button or other actions here if needed (future enhancement)
            # del_button = ctk.CTkButton(voice_frame, text="Delete", width=60, fg_color="red")
            # del_button.pack(side="right", padx=10)

    def show_history_frame(self):
        self.clear_content_frame()
        self.set_active_nav_button("History")
        ctk.CTkLabel(self.content_frame, text="Generation History", font=ctk.CTkFont(size=28, weight="bold")).pack(
            pady=(10, 20), anchor="w", padx=20)

        history_scroll_frame = ctk.CTkScrollableFrame(self.content_frame, fg_color=SECONDARY_COLOR)
        history_scroll_frame.pack(fill="both", expand=True, padx=20, pady=10)

        if not self.current_user or 'api_key' not in self.current_user:
            ctk.CTkLabel(history_scroll_frame, text="Login to see history.").pack(pady=10)
            return

        try:
            import requests
            response = requests.get(f"{API_BASE_URL}/user/history/{self.current_user['api_key']}")
            if response.status_code == 200:
                history_items = response.json()
                if not history_items:
                    ctk.CTkLabel(history_scroll_frame, text="No generation history yet.").pack(pady=10)
                    return

                for item in history_items:
                    item_frame = ctk.CTkFrame(history_scroll_frame, fg_color=PRIMARY_COLOR, corner_radius=5)
                    item_frame.pack(fill="x", pady=5, padx=5)

                    text_preview = item['text_input'][:80] + "..." if len(item['text_input']) > 80 else item[
                        'text_input']
                    info_text = f"Text: {text_preview}\nVoice: {item['voice_name']} | Generated: {item['generated_at']}"
                    ctk.CTkLabel(item_frame, text=info_text, justify="left", anchor="w").pack(side="left", padx=10,
                                                                                              pady=5, fill="x",
                                                                                              expand=True)

                    def play_history_item_action(path=item['audio_file_path']):  # Capture path in closure
                        self.current_audio_filepath = path  # Set for main play function
                        self.play_audio()

                    play_btn = ctk.CTkButton(item_frame, text="▶", width=30,
                                             command=lambda p=item['audio_file_path']: play_history_item_action(p))
                    play_btn.pack(side="right", padx=5)

            else:
                ctk.CTkLabel(history_scroll_frame, text=f"Error loading history: {response.json().get('detail')}",
                             text_color="orange").pack(pady=10)
        except requests.exceptions.RequestException as e:
            ctk.CTkLabel(history_scroll_frame, text=f"Connection error: {e}", text_color="red").pack(pady=10)

    def show_subscription_frame(self):
        self.clear_content_frame()
        self.set_active_nav_button("Subscription")
        ctk.CTkLabel(self.content_frame, text="Subscription Plans", font=ctk.CTkFont(size=28, weight="bold")).pack(
            pady=(10, 10), anchor="w", padx=20)

        current_plan_text = f"Your current plan: {self.current_user['subscription_tier']}"
        if self.current_user.get('subscription_expiry'):
            current_plan_text += f" (Expires: {self.current_user['subscription_expiry']})"
        ctk.CTkLabel(self.content_frame, text=current_plan_text, font=ctk.CTkFont(size=16)).pack(pady=(0, 20),
                                                                                                 anchor="w", padx=20)

        plans_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        plans_frame.pack(fill="both", expand=True, padx=20, pady=10)
        plans_frame.grid_columnconfigure((0, 1, 2), weight=1)  # 3 columns for plans

        plans_data = [
            {"name": "Basic", "price": "Free", "gens": "10/day",
             "features": ["Standard voices", "Limited languages", "Community support"]},
            {"name": "Premium", "price": "$9.99/mo", "gens": "100/day",
             "features": ["All standard voices", "Voice Cloning (Simulated)", "Expanded languages",
                          "Priority email support"]},
            {"name": "Ultimate", "price": "$29.99/mo", "gens": "1000/day",
             "features": ["All voices + early access", "Advanced Voice Cloning (Simulated)", "All languages & accents",
                          "Dedicated support", "API Access (Simulated)"]},
        ]

        for i, plan in enumerate(plans_data):
            plan_card = ctk.CTkFrame(plans_frame, fg_color=SECONDARY_COLOR, corner_radius=10, border_width=2,
                                     border_color=ACCENT_COLOR if plan['name'] == self.current_user[
                                         'subscription_tier'] else PRIMARY_COLOR)
            plan_card.grid(row=0, column=i, sticky="nsew", padx=10, pady=10)
            plan_card.grid_rowconfigure(4, weight=1)  # Push button to bottom

            ctk.CTkLabel(plan_card, text=plan['name'], font=ctk.CTkFont(size=22, weight="bold"),
                         text_color=ACCENT_COLOR).pack(pady=(15, 5))
            ctk.CTkLabel(plan_card, text=plan['price'], font=ctk.CTkFont(size=18)).pack(pady=5)
            ctk.CTkLabel(plan_card, text=f"Generations: {plan['gens']}", font=ctk.CTkFont(size=14)).pack(pady=5)

            ctk.CTkLabel(plan_card, text="Features:", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(10, 5))
            for feature in plan['features']:
                ctk.CTkLabel(plan_card, text=f"• {feature}", font=ctk.CTkFont(size=12), wraplength=200,
                             justify="left").pack(anchor="w", padx=15)

            if plan['name'] == self.current_user['subscription_tier']:
                ctk.CTkButton(plan_card, text="Current Plan", state="disabled", height=35).pack(side="bottom", fill="x",
                                                                                                padx=15, pady=15)
            else:
                subscribe_button = ctk.CTkButton(plan_card, text=f"Subscribe to {plan['name']}",
                                                 command=lambda p=plan['name']: self.handle_subscribe(p),
                                                 fg_color=ACCENT_COLOR, hover_color=BUTTON_HOVER_COLOR, height=35)
                subscribe_button.pack(side="bottom", fill="x", padx=15, pady=15)

        self.sub_status_label = ctk.CTkLabel(self.content_frame, text="")
        self.sub_status_label.pack(pady=10)

    def handle_subscribe(self, tier_name):
        # Simulate payment details popup
        payment_dialog = ctk.CTkToplevel(self)
        payment_dialog.title(f"Subscribe to {tier_name}")
        payment_dialog.geometry("400x300")
        payment_dialog.transient(self)  # Keep on top of main window
        payment_dialog.grab_set()  # Modal

        ctk.CTkLabel(payment_dialog, text=f"Confirm Subscription to {tier_name}", font=ctk.CTkFont(size=18)).pack(
            pady=10)
        ctk.CTkLabel(payment_dialog, text="Simulated Payment Gateway", font=ctk.CTkFont(size=12)).pack(pady=5)

        card_entry = ctk.CTkEntry(payment_dialog, placeholder_text="Card Number (e.g., 4242...)")
        card_entry.pack(pady=5, padx=20, fill="x")
        expiry_entry = ctk.CTkEntry(payment_dialog, placeholder_text="MM/YY")
        expiry_entry.pack(pady=5, padx=20, fill="x")
        cvv_entry = ctk.CTkEntry(payment_dialog, placeholder_text="CVV")
        cvv_entry.pack(pady=5, padx=20, fill="x")

        def confirm_payment_action():
            # Actual payment processing would happen here
            # For simulation, we just send to backend
            payment_details = {
                "card_number": card_entry.get(),
                "expiry": expiry_entry.get(),
                "cvv": cvv_entry.get()
            }
            payment_dialog.destroy()  # Close dialog first

            try:
                import requests
                response = requests.post(f"{API_BASE_URL}/subscribe",
                                         json={"user_id": self.current_user['id'],
                                               "tier": tier_name,
                                               "payment_details": payment_details})
                if response.status_code == 200:
                    res_data = response.json()
                    self.current_user = res_data['user']  # Update local user data
                    self.sub_status_label.configure(text=res_data['message'], text_color="green")
                    messagebox.showinfo("Success", res_data['message'])
                    self.update_user_info_display()
                    self.show_subscription_frame()  # Refresh view
                else:
                    error_detail = response.json().get("detail", "Subscription failed.")
                    self.sub_status_label.configure(text=error_detail, text_color="red")
                    messagebox.showerror("Error", error_detail)
            except requests.exceptions.RequestException as e:
                self.sub_status_label.configure(text=f"Connection error: {e}", text_color="red")
                messagebox.showerror("Connection Error", f"Could not process subscription: {e}")

        confirm_btn = ctk.CTkButton(payment_dialog, text="Confirm & Pay (Simulated)", command=confirm_payment_action,
                                    fg_color=ACCENT_COLOR)
        confirm_btn.pack(pady=20)
        cancel_btn = ctk.CTkButton(payment_dialog, text="Cancel", command=payment_dialog.destroy)
        cancel_btn.pack(pady=5)


# --- Main Application Execution ---
if __name__ == "__main__":
    # Start FastAPI server in a separate thread
    fastapi_thread = threading.Thread(target=run_fastapi_server, daemon=True)
    fastapi_thread.start()

    # Allow server to start
    print("Waiting for FastAPI server to start...")
    time.sleep(2)

    app_gui = NovaVoiceApp()
    app_gui.mainloop()