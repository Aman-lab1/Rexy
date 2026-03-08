import requests
import asyncio
import os
import pygame
import io
import numpy as np
from piper import PiperVoice

REXY_URL = "http://127.0.0.1:8000/process"
VOICE_PATH = "voices/en_US-lessac-medium.onnx"

pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)

async def speak_piper(text: str):
    print(f"[PIPER TTS] Speaking: {text[:50]}{'...' if len(text) > 50 else ''}")
    
    if not os.path.exists(VOICE_PATH):
        print(f"Voice missing: {VOICE_PATH}")
        return
    
    try:
        # Load Piper voice directly
        voice = PiperVoice.load(VOICE_PATH)
        
        # Synthesize
        audio = voice(text, wav16khz=True)
        
        # Convert to pygame format
        audio_np = np.frombuffer(audio, dtype=np.int16)
        audio_bytes = audio_np.tobytes()
        
        # Play
        pygame.mixer.music.load(io.BytesIO(audio_bytes))
        pygame.mixer.music.play()
        
        while pygame.mixer.music.get_busy():
            await asyncio.sleep(0.1)
            
        print(" Voice playback complete!")
            
    except Exception as e:
        print(f"TTS Error: {e}")

def ask_rexy(command: str) -> str:
    try:
        resp = requests.post(REXY_URL, json={"command": command}, timeout=10)
        data = resp.json()
        return data.get("result", {}).get("output", "No response") or str(data)
    except:
        return "Rexy offline"

async def main():
    print("Rexy Piper Voice (60MB premium). 'exit' to quit.")
    
    while True:
        cmd = input("\nYou: ")
        if cmd.lower() in {"exit", "quit"}:
            break
        
        reply = ask_rexy(cmd)
        print("Rexy:", reply)
        await speak_piper(reply)

if __name__ == "__main__":
    asyncio.run(main())
