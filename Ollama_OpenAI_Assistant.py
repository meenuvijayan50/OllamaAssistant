import argparse
import queue
import sys
import sounddevice as sd
import json
import requests
import time
import pyttsx3
from concurrent.futures import ThreadPoolExecutor
from vosk import Model, KaldiRecognizer
import threading

# Global variables and events
q = queue.Queue()
stop_flag = threading.Event()
tts_active = threading.Event()
engine = pyttsx3.init()

# Wake word for activation
WAKE_WORD = "hello"

def callback(indata, frames, time, status):
    if status:
        print(status, file=sys.stderr)
    q.put(bytes(indata))

def vosk_listen(args):
    device_info = sd.query_devices(args.device, "input")
    args.samplerate = int(device_info["default_samplerate"])

    model = Model(lang=args.model if args.model else "en-us")

    with sd.RawInputStream(samplerate=args.samplerate, blocksize=8000, device=args.device,
                           dtype="int16", channels=1, callback=callback):
        rec = KaldiRecognizer(model, args.samplerate)

        while not stop_flag.is_set():
            data = q.get()
            if rec.AcceptWaveform(data):
                result_json = json.loads(rec.Result())
                result_text = result_json["text"]
                if result_text:
                    print(f"Recognized: {result_text}")
                    return result_text

def handle_recognized_text(text):
    if "stop" in text.lower():
        stop_flag.set()
        engine.stop()
        print("Stopping TTS and resetting...")
    elif WAKE_WORD in text.lower():
        print("Wake word detected, listening for command...")
        command = listen_for_command()
        if command:
            respond_to_text(command)

def listen_for_command():
    # Continue listening for a command after wake word
    while not stop_flag.is_set():
        text = vosk_listen(args)
        if text:
            if "stop" in text.lower():
                stop_flag.set()
                print("Exiting...")
                break
            elif not tts_active.is_set():
                return text
            else:
                print("TTS active, waiting...")

def respond_to_text(text):
    with ThreadPoolExecutor() as executor:
        ollama_future = executor.submit(get_ollama_response, text)
        openai_future = executor.submit(get_openai_response, text)

        ollama_response = ollama_future.result()
        openai_response = openai_future.result()

        print("\nOllama LLM Response:")
        print(ollama_response)

        print("\nOpenAI Response:")
        print(openai_response)

        # Speak both responses
        speak(ollama_response)
        speak(openai_response)

def get_ollama_response(prompt):
    ollama_url = "http://localhost:11434/api/generate"
    headers = {"Content-Type": "application/json"}
    data = {
        "model": "tinydolphin",
        "prompt": prompt,
        "stream": False,
        "system": "You are a helpful assistant. You will answer the question in 30 to 40 words.",
        "options": {
            "num_keep": 0,
            "top_k": 10, 
            "temperature": 0.8,
        }
    }

    response, total_time = measure_total_time(requests.post, ollama_url, headers=headers, json=data)
    full_response = process_ollama_response(response)

    print(f"Ollama LLM response (time taken: {total_time * 1000:.2f} ms): {full_response}")
    return full_response

def process_ollama_response(response):
    response_lines = response.iter_lines()
    full_response = ""
    for line in response_lines:
        if line:
            response_json = json.loads(line)
            full_response += response_json.get('response', '')
    return full_response

def get_openai_response(prompt):
    openai_url = "https://api.openai.com/v1/chat/completions"
    api_key = "OPENAI_KEY"  # Hardcoded OpenAI API key
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "gpt-3.5-turbo",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 100
    }

    try:
        response, total_time = measure_total_time(
            requests.post, openai_url, headers=headers, json=data
        )
        result = process_openai_response(response)
        print(f"Time taken by OpenAI: {total_time * 1000:.2f} ms")
        return result
    except requests.exceptions.RequestException as e:
        return f"OpenAI API Request Failed: {str(e)}"

def process_openai_response(response):
    if response.status_code == 200:
        return response.json().get("choices", [{}])[0].get("message", {}).get("content", "No response content.")
    else:
        return f"Error: {response.status_code} - {response.text}"

def measure_total_time(func, *args, **kwargs):
    start_time = time.perf_counter()
    result = func(*args, **kwargs)
    end_time = time.perf_counter()
    total_time = end_time - start_time
    return result, total_time

def speak(text):
    tts_active.set()  # TTS is active
    
    engine.setProperty('rate', 150)
    engine.setProperty('volume', 0.9)
    engine.setProperty('voice', 'english+f3')
    
    engine.say(text)
    engine.runAndWait()
    
    tts_active.clear()  # TTS is done

def continuous_chat_with_vosk(args):
    print("Say 'stop' to end the chat. Use the wake word 'hello' to activate.")

    while not stop_flag.is_set():
        recognized_text = vosk_listen(args)
        if recognized_text:
            handle_recognized_text(recognized_text)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Vosk with Ollama and OpenAI Integration")
    parser.add_argument("-d", "--device", type=int, help="input device ID")
    parser.add_argument("-m", "--model", type=str, default="en-us", help="language model")
    args = parser.parse_args()

    continuous_chat_with_vosk(args)
