# NovaVoice AI 🎤

**Version:** 1.0.0 Ultimate

NovaVoice AI is a full-stack, desktop Text-to-Speech (TTS) application that combines a modern Python GUI with a powerful backend API. It provides a complete, self-contained environment for generating, managing, and listening to AI-powered speech, complete with user accounts, a simulated subscription model, and voice cloning capabilities.


*(Replace the link above with a real screenshot of your application running)*

## ✨ Features

- **Modern Desktop GUI:** Built with **CustomTkinter** for a sleek, modern, and responsive user interface with a dark theme.
- **Full User Authentication:**
    - Secure user registration and login system.
    - Password hashing for security.
- **Powerful Speech Synthesis:**
    - Generate high-quality speech from text.
    - Control voice parameters like speed.
    - (Simulated) control over pitch and emotion for advanced voice-over work.
- **Voice Lab:**
    - **Pre-set Voices:** A library of built-in voices to get started immediately.
    - **Voice Cloning (Simulated):** "Clone" a voice by uploading an audio sample. This feature demonstrates the workflow of a premium voice cloning service.
    - **My Voices:** A personal library to manage your custom-cloned voices.
- **Generation History:**
    - Automatically saves a history of all your generated audio.
    - Re-play audio directly from the history panel.
- **Simulated Subscription Model:**
    - **Tiers:** Basic (Free), Premium, and Ultimate tiers.
    - **Usage Limits:** Daily generation limits for the Basic tier.
    - **Feature Gating:** Premium features like Voice Cloning are restricted to higher tiers.
    - **Simulated Payment:** A complete, (but simulated), subscription and payment workflow.
- **Local API Backend:**
    - Built with **FastAPI** for a high-performance, robust, and scalable local API.
    - The GUI communicates with the FastAPI server, separating the UI from the business logic.
- **Database Persistence:**
    - Uses **SQLite** to store all user data, voice profiles, and generation history.
- **Local Audio Management:**
    - Generated audio is saved locally.
    - Built-in audio playback.
    - Easy download option for generated `.wav` files.

## 🛠️ Tech Stack

- **Frontend (GUI):**
    - **[CustomTkinter](https://github.com/TomSchimansky/CustomTkinter)**: For the modern graphical user interface.
    - **Pillow**: For image handling (if icons were used).
- **Backend (API):**
    - **[FastAPI](https://fastapi.tiangolo.com/)**: For the robust, high-performance REST API.
    - **[Uvicorn](https://www.uvicorn.org/)**: As the ASGI server to run FastAPI.
    - **Pydantic**: For data validation and settings management.
- **Text-to-Speech Engine:**
    - **[pyttsx3](https://pypi.org/project/pyttsx3/)**: A cross-platform TTS library for local speech generation.
- **Audio Playback:**
    - **[playsound](https://pypi.org/project/playsound/)**: For simple, cross-platform audio file playback.
- **Database:**
    - **[SQLite](https://www.sqlite.org/index.html)**: For local, file-based database management.

## 🚀 Getting Started

Follow these instructions to set up and run the NovaVoice AI application on your local machine.

### Prerequisites

- Python 3.7+

### Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-username/novavoice-ai.git
    cd novavoice-ai
    ```

2.  **Create and activate a virtual environment (recommended):**
    - **Windows:**
      ```bash
      python -m venv venv
      .\venv\Scripts\activate
      ```
    - **macOS / Linux:**
      ```bash
      python3 -m venv venv
      source venv/bin/activate
      ```

3.  **Install the required dependencies:**
    A `requirements.txt` file is the best way to manage dependencies. Create a file named `requirements.txt` with the following content:

    **`requirements.txt`**
    ```
    customtkinter
    fastapi
    uvicorn[standard]
    pydantic
    pyttsx3
    playsound==1.2.2
    requests
    Pillow
    ```
    *Note: `playsound` version `1.2.2` is specified for better compatibility and to avoid common blocking issues.*

    Now, install the packages using pip:
    ```bash
    pip install -r requirements.txt
    ```

### Running the Application

To run the application, simply execute the main Python script. This will automatically start the FastAPI backend server in a background thread and then launch the CustomTkinter GUI.

```bash
python your_script_name.py
```
*(Replace `your_script_name.py` with the actual name of the Python file)*

You will see logs from the Uvicorn server in your terminal, indicating that the backend is running (usually on `http://127.0.0.1:8008`). The desktop application window will then appear.

## 🏛️ Application Architecture

The application runs as two main components in parallel:

1.  **FastAPI Backend Server**: A separate thread runs a Uvicorn server hosting the FastAPI application. It handles all business logic, including:
    - User authentication (`/login`, `/register`).
    - Database operations (CRUD for users, voices, history).
    - TTS generation requests (`/tts/generate`).
    - Voice cloning and management (`/voice/clone`).
2.  **CustomTkinter Frontend (GUI)**: The main thread runs the desktop application. The GUI **does not** perform any business logic itself. Instead, it acts as a client that sends HTTP requests to the local FastAPI backend to perform actions and retrieve data. This architecture cleanly separates the user interface from the core logic, making the application more robust and easier to maintain.

## 📁 File Structure

When you run the application, it will generate the following files and directories in the same folder as the script:

```
.
├── your_script_name.py         # The main application script
├── novavoice_ai.db             # The SQLite database file
├── generated_audio/            # Directory to store all generated .wav files
│   ├── [uuid].wav
│   └── ...
└── cloned_voice_samples/       # Directory to store uploaded audio samples for cloning
    ├── [uuid]_[filename].wav
    └── ...
```

## 📝 License

This project is licensed under the MIT License. See the `LICENSE` file for details.
