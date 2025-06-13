import socket
import pyaudio
from vosk import Model, KaldiRecognizer
import json
import time
import requests
import prompt
from flask import Flask, send_file
from gtts import gTTS
import threading
import os
from gigachat import GigaChat
import re

# Инициализация Flask
app = Flask(__name__)
AUDIO_FILENAME = "response.mp3"
FLASK_PORT = 5005
PLAYER_URL = "http://IP_YOU_ESP32/play"

# Настройки UDP
UDP_IP = "0.0.0.0"
UDP_PORT = 3333

modelGiga = GigaChat(
        credentials="YOU_TOKEN_GIGACHAT",
        # model="GigaChat-2-Max",  # Версия модели
        model="GigaChat-2-preview",  # Версия модели
        verify_ssl_certs=False,  # Отключение проверки SSL (не рекомендуется для прода)
    )

response = modelGiga.get_models()


# Инициализация Vosk
model = Model("./vosk-model-small-ru-0.22")
recognizer = KaldiRecognizer(model, 16000)
recognizer.SetWords(True)

# Инициализация аудиовыхода
p = pyaudio.PyAudio()
stream = p.open(
    format=pyaudio.paInt16,
    channels=1,
    rate=16000,
    output=True
)

# Настройка UDP сокета
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))
sock.settimeout(0.1)  # Таймаут для проверки пауз

# Переменные для управления состоянием
BUFFERING = False
accumulated_text = []
last_voice_time = time.time()
SILENCE_THRESHOLD = 3.0  # 3 секунды тишины
TRIGGER_WORD = "баба"

def run_flask():
    """Запуск Flask в отдельном потоке"""
    app.run(host='0.0.0.0', port=FLASK_PORT, debug=False, use_reloader=False)

# Запуск Flask в фоновом режиме
flask_thread = threading.Thread(target=run_flask, daemon=True)
flask_thread.start()

system_prompt = (
    "Ты бабушка и у тебя есть внук Марк.\n"
    "Ты общаеешься с ребенком которому 4 года и зовут его Марк"
    "Отвечай на вопрос очень кратко. Не больше двух предложений"
    "Ответ должен быть понятен ребеку 4 лет."
    "Вопрос: "
)

@app.route('/audio')
def serve_audio():
    """Маршрут для скачивания аудиофайла"""
    return send_file(AUDIO_FILENAME, mimetype='audio/mp3')

def clean_text(text):
    # Удаляем все вхождения слова "кузя" (с любым регистром)
    cleaned = re.sub(r'\баба\b', '', text, flags=re.IGNORECASE)
    
    # Удаляем все специальные символы (оставляем только буквы, цифры и пробелы)
    cleaned = re.sub(r'[^a-zA-Zа-яА-ЯёЁ0-9\s]', '', cleaned)
    
    # Удаляем лишние пробелы и обрезаем строку
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

def send_to_llama(message):
    """Отправляет сообщение на сервер Llama и обрабатывает ответ"""
    try:
        reply = modelGiga.chat(system_prompt + clean_text(message))
        print(reply)
        # Генерация MP3 из ответа
        tts = gTTS(text=reply.choices[0].message.content, lang='ru')
        tts.save(AUDIO_FILENAME)
        print(f"Аудиофайл сохранён: {AUDIO_FILENAME}")
        
        # Получение IP сервера для формирования URL
        host_ip = socket.gethostbyname(socket.gethostname())
        audio_url = f"http://{host_ip}:{FLASK_PORT}/audio"
        
        # Отправка команды на воспроизведение
        requests.get(f"{PLAYER_URL}", timeout=2)
        print(f"Отправлен запрос на воспроизведение: {PLAYER_URL}?url={audio_url}")
        
        return reply
        
    except Exception as e:
        print(f"\nОшибка при обработке запроса: {str(e)}")
        return f"Ошибка: {str(e)}"

print("Сервер запущен. Ожидание данных...")

while True:
    try:
        # Получение аудиоданных
        data, addr = sock.recvfrom(4096)
        
        # Конвертация 32-битных данных в 16-битные
        audio_data = []
        for i in range(0, len(data), 4):
            sample = int.from_bytes(data[i:i+4], byteorder="little", signed=True)
            audio_data.append(sample // 32768)
        
        audio_bytes = bytes(bytearray([x for s in audio_data for x in s.to_bytes(2, 'little', signed=True)]))
        
        # Воспроизведение аудио
        # stream.write(audio_bytes)
        
        # Распознавание речи
        if recognizer.AcceptWaveform(audio_bytes):
            result = json.loads(recognizer.Result())
            if 'text' in result and result['text']:
                text = result['text']
                print("\nРаспознано:", text)
                
                # Проверка триггерного слова
                if TRIGGER_WORD in text.lower() and not BUFFERING:
                    BUFFERING = True
                    accumulated_text = [text]
                    last_voice_time = time.time()
                    print("Начата буферизация...")
                
                # Добавление текста в буфер
                elif BUFFERING:
                    accumulated_text.append(text)
                    last_voice_time = time.time()
        
        # Проверка частичных результатов
        partial = json.loads(recognizer.PartialResult())
        if 'partial' in partial and partial['partial']:
            partial_text = partial['partial']
            print(f"\rТекущая речь: {partial_text}", end="", flush=True)
            
            # Обновление времени активности при распознавании
            if BUFFERING:
                last_voice_time = time.time()
    
    except socket.timeout:
        # Обработка паузы в буферизации
        if BUFFERING and (time.time() - last_voice_time) >= SILENCE_THRESHOLD:
            full_message = " ".join(accumulated_text)
            print(f"\n\nОтправка запроса: {full_message}")
            send_to_llama(full_message)
            
            # Сброс состояния
            BUFFERING = False
            accumulated_text = []
    
    # Обработка паузы при активной буферизации
    if BUFFERING and (time.time() - last_voice_time) >= SILENCE_THRESHOLD:
        full_message = " ".join(accumulated_text)
        print(f"\n\nОтправка запроса: {full_message}")
        send_to_llama(full_message)
        
        # Сброс состояния
        BUFFERING = False
        accumulated_text = []