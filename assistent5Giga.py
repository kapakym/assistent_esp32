# Импорт необходимых библиотек
import socket  # Для работы с сетевыми сокетами (UDP)
import pyaudio  # Для работы с аудио (в данном случае не используется напрямую)
from vosk import Model, KaldiRecognizer  # Распознавание речи
import json  # Обработка JSON данных
import time  # Работа со временем и задержками
import requests  # Отправка HTTP запросов
from flask import Flask, send_file  # Веб-сервер для отдачи файлов
from gtts import gTTS  # Google Text-to-Speech для генерации речи
import threading  # Многопоточность
from gigachat import GigaChat  # API для работы с GigaChat
import re  # Регулярные выражения для обработки текста

# Инициализация Flask приложения
app = Flask(__name__)
# Имя файла для сохранения сгенерированного аудио
AUDIO_FILENAME = "response.mp3"
# Порт для Flask сервера
FLASK_PORT = 5005
# URL внешнего плеера для воспроизведения аудио
PLAYER_URL = "http://IP_ESP_32/play"

# Настройки UDP сокета
UDP_IP = "0.0.0.0"  # Слушать все сетевые интерфейсы
UDP_PORT = 3333     # Порт для получения аудио

# Инициализация GigaChat клиента с учетными данными
modelGiga = GigaChat(
    credentials=YOU_TOKEN,
    model="GigaChat-2-preview",  # Используемая модель
    verify_ssl_certs=False,      # Отключение проверки SSL сертификатов
)

# Проверка доступных моделей (не используется далее)
response = modelGiga.get_models()

# Загрузка модели Vosk для распознавания русской речи
model = Model("./vosk-model-small-ru-0.22")
# Инициализация распознавателя с частотой 16000 Гц
recognizer = KaldiRecognizer(model, 16000)
# Включение возвращения распознанных слов
recognizer.SetWords(True)

# Инициализация PyAudio (хотя в коде не используется для воспроизведения)
p = pyaudio.PyAudio()
# Создание аудиопотока (не используется в текущей реализации)
stream = p.open(
    format=pyaudio.paInt16,  # 16-битный формат
    channels=1,              # Моно
    rate=16000,              # Частота дискретизации
    output=True              # Поток вывода
)

# Настройка UDP сокета для приема данных
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
# Привязка сокета к IP и порту
sock.bind((UDP_IP, UDP_PORT))
# Установка таймаута для операций с сокетом
sock.settimeout(0.1)  # 100 мс

# Флаг состояния буферизации речи
BUFFERING = False
# Буфер для накопления распознанного текста
accumulated_text = []
# Время последней речевой активности
last_voice_time = time.time()
# Порог тишины для завершения ввода (3 секунды)
SILENCE_THRESHOLD = 3.0
# Ключевое слово для активации ассистента
TRIGGER_WORD = "смарт"

# История диалога для поддержки контекста
conversation_history = []
# Максимальное количество пар вопрос-ответ в истории
MAX_HISTORY_PAIRS = 3
# Время последнего взаимодействия
LAST_INTERACTION_TIME = time.time()
# Таймаут очистки истории (5 минут)
HISTORY_TIMEOUT = 300

# Системный промпт с инструкциями для модели
system_prompt = (
    "Ты умная колонка, тебя зовут Смарт.\n"
    "Отвечай на вопросы очень кратко. Не больше двух предложений. Предложения должны быть очень компактными\n"
    "Ответ должен быть понятен необразованному человеку.\n"
    "Ты должна уметь поддержать разговор.\n"
)

# Функция для запуска Flask в отдельном потоке
def run_flask():
    app.run(host='0.0.0.0', port=FLASK_PORT, debug=False, use_reloader=False)

# Запуск Flask сервера в фоновом режиме
flask_thread = threading.Thread(target=run_flask, daemon=True)
flask_thread.start()

# Функция очистки текста от триггерного слова и спецсимволов
def clean_text(text):
    # Удаление триггерного слова (регистронезависимо)
    cleaned = re.sub(r'\b' + TRIGGER_WORD + r'\b', '', text, flags=re.IGNORECASE)
    # Удаление спецсимволов
    cleaned = re.sub(r'[^a-zA-Zа-яА-ЯёЁ0-9\s]', '', cleaned)
    # Удаление лишних пробелов
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

# Функция очистки истории диалога при простое
def update_conversation_history():
    global conversation_history, LAST_INTERACTION_TIME
    current_time = time.time()
    # Проверка таймаута
    if current_time - LAST_INTERACTION_TIME > HISTORY_TIMEOUT:
        conversation_history = []
        print("\nИстория диалога очищена из-за длительного простоя")
    LAST_INTERACTION_TIME = current_time

# Основная функция обработки запросов
def send_to_llama(message):
    global conversation_history
    
    try:
        # Обновление истории
        update_conversation_history()
        
        # Очистка входящего сообщения
        user_message = clean_text(message)
        print(f"Очищенный запрос: {user_message}")
        
        # Формирование контекста диалога
        messages = []
        
        # Добавление системного промпта при первом запросе
        if not conversation_history:
            messages.append({"role": "system", "content": system_prompt})
        
        # Добавление истории диалога
        messages.extend(conversation_history)
        
        # Добавление текущего запроса
        messages.append({"role": "user", "content": user_message})
        
        # Отправка запроса в GigaChat
        reply = modelGiga.chat({"messages":messages})
        assistant_reply = reply.choices[0].message.content
        
        # Обновление истории
        conversation_history.append({"role": "user", "content": user_message})
        conversation_history.append({"role": "assistant", "content": assistant_reply})
        
        # Ограничение размера истории
        if len(conversation_history) > MAX_HISTORY_PAIRS * 2:
            conversation_history = conversation_history[-(MAX_HISTORY_PAIRS * 2):]
            print(f"История сокращена до последних {MAX_HISTORY_PAIRS} пар")
        
        print(f"\nОтвет модели: {assistant_reply}")
        
        # Генерация аудио из текста
        tts = gTTS(text=assistant_reply, lang='ru')
        tts.save(AUDIO_FILENAME)
        print(f"Аудиофайл сохранён: {AUDIO_FILENAME}")
        
        # Формирование URL для аудио
        host_ip = socket.gethostbyname(socket.gethostname())
        audio_url = f"http://{host_ip}:{FLASK_PORT}/audio"
        
        # Отправка команды на воспроизведение
        requests.get(f"{PLAYER_URL}", timeout=2)
        print(f"Отправлен запрос на воспроизведение: {PLAYER_URL}?url={audio_url}")
        
        return reply
        
    except Exception as e:
        print(f"\nОшибка при обработке запроса: {str(e)}")
        return f"Ошибка: {str(e)}"

# Маршрут Flask для отдачи аудиофайла
@app.route('/audio')
def serve_audio():
    return send_file(AUDIO_FILENAME, mimetype='audio/mp3')

print("Сервер запущен. Ожидание данных...")

# Основной цикл обработки
while True:
    try:
        # Получение аудиоданных через UDP
        data, addr = sock.recvfrom(4096)
        
        # Конвертация 32-битных данных в 16-битные
        audio_data = []
        for i in range(0, len(data), 4):
            sample = int.from_bytes(data[i:i+4], byteorder="little", signed=True)
            audio_data.append(sample // 32768)  # Масштабирование
        
        # Формирование байтового буфера
        audio_bytes = bytes(bytearray([x for s in audio_data for x in s.to_bytes(2, 'little', signed=True)]))
        
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
        
        # Обработка частичных результатов
        partial = json.loads(recognizer.PartialResult())
        if 'partial' in partial and partial['partial']:
            partial_text = partial['partial']
            # Вывод текущего распознавания
            print(f"\rТекущая речь: {partial_text}", end="", flush=True)
            
            # Обновление времени активности
            if BUFFERING:
                last_voice_time = time.time()
    
    except socket.timeout:
        # Обработка паузы при буферизации
        if BUFFERING and (time.time() - last_voice_time) >= SILENCE_THRESHOLD:
            full_message = " ".join(accumulated_text)
            print(f"\n\nОтправка запроса: {full_message}")
            send_to_llama(full_message)
            
            # Сброс состояния
            BUFFERING = False
            accumulated_text = []
    
    # Дополнительная проверка паузы
    if BUFFERING and (time.time() - last_voice_time) >= SILENCE_THRESHOLD:
        full_message = " ".join(accumulated_text)
        print(f"\n\nОтправка запроса: {full_message}")
        send_to_llama(full_message)
        
        # Сброс состояния
        BUFFERING = False
        accumulated_text = []