#include <WiFi.h>
#include <WiFiUdp.h>
#include <driver/i2s.h>
#include <WebServer.h>
#include <AudioGeneratorMP3.h>
#include <AudioFileSourceHTTPStream.h>
#include <AudioOutputI2S.h>

// Настройки сети
const char *ssid = "pav";
const char *password = "YOU PASSWORD";
const char *audio_url = "http://YOU_SERVER_IP:5005/audio";
const char *targetIP = "YOU_SERVER_IP";
const int udpPort = 3333;

// Веб-сервер на порту 80
WebServer server(80);

// Аудиокомпоненты
AudioGeneratorMP3 *mp3 = nullptr;
AudioFileSourceHTTPStream *file = nullptr;
AudioOutputI2S *out = nullptr;

// I2S микрофона
#define I2S_MIC_SAMPLE_RATE 32000
#define I2S_MIC_SAMPLE_BITS 16
#define I2S_READ_LEN 1024

// Пины I2S
#define I2S_MIC_BCK_PIN 14
#define I2S_MIC_WS_PIN 15
#define I2S_MIC_DATA_PIN 32
#define I2S_SPK_BCK_PIN 27
#define I2S_SPK_WS_PIN 26
#define I2S_SPK_DATA_PIN 25

// Буфер для аудиосэмплов
DRAM_ATTR static int16_t i2s_readraw_buff[I2S_READ_LEN];
WiFiUDP udp;

// Флаг для управления воспроизведением
bool shouldPlay = false;

void startAudioPlayback()
{
  // Остановить предыдущее воспроизведение
  if (mp3 && mp3->isRunning())
  {
    mp3->stop();
    delete mp3;
    delete file;
    delete out;
  }

  // Инициализация аудиовыхода
  out = new AudioOutputI2S(1);
  out->SetPinout(I2S_SPK_BCK_PIN, I2S_SPK_WS_PIN, I2S_SPK_DATA_PIN);
  out->SetGain(0.9);
  out->SetOutputModeMono(true);

  // Запуск воспроизведения
  file = new AudioFileSourceHTTPStream(audio_url);
  mp3 = new AudioGeneratorMP3();

  if (mp3->begin(file, out))
  {
    Serial.println("Audio playback started");
  }
  else
  {
    Serial.println("Failed to start playback");
    delete mp3;
    mp3 = nullptr;
    delete file;
    file = nullptr;
    delete out;
    out = nullptr;
  }
}

void handlePlay()
{
  shouldPlay = true;
  server.send(200, "text/plain", "Play command received");
}

void setup()
{
  Serial.begin(115200);

  // Подключение к WiFi
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED)
    delay(500);
  Serial.println("\nWiFi connected");
  Serial.print("IP address: ");
  Serial.println(WiFi.localIP());

  // Инициализация I2S для микрофона
  i2s_config_t i2s_config = {
      .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
      .sample_rate = I2S_MIC_SAMPLE_RATE,
      .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
      .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
      .communication_format = I2S_COMM_FORMAT_STAND_I2S,
      .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
      .dma_buf_count = 4,
      .dma_buf_len = 512,
      .use_apll = false,
      .tx_desc_auto_clear = false,
      .fixed_mclk = 0};

  i2s_pin_config_t pin_config = {
      .bck_io_num = I2S_MIC_BCK_PIN,
      .ws_io_num = I2S_MIC_WS_PIN,
      .data_out_num = -1,
      .data_in_num = I2S_MIC_DATA_PIN};

  i2s_driver_install(I2S_NUM_0, &i2s_config, 0, NULL);
  i2s_set_pin(I2S_NUM_0, &pin_config);

  // Настройка HTTP сервера
  server.on("/play", HTTP_GET, handlePlay);
  server.begin();
  Serial.println("HTTP server started");
}

void loop()
{
  // Обработка HTTP запросов
  server.handleClient();

  // Запуск воспроизведения по флагу
  if (shouldPlay)
  {
    shouldPlay = false;
    startAudioPlayback();
  }

  // Отправка аудио с микрофона
  size_t bytes_read;
  i2s_read(I2S_NUM_0, i2s_readraw_buff, I2S_READ_LEN * sizeof(int16_t), &bytes_read, portMAX_DELAY);

  if (bytes_read > 0)
  {
    udp.beginPacket(targetIP, udpPort);
    udp.write((uint8_t *)i2s_readraw_buff, bytes_read);
    udp.endPacket();
  }

  // Управление воспроизведением
  if (mp3 && mp3->isRunning())
  {
    if (!mp3->loop())
    {
      mp3->stop();
      delete mp3;
      mp3 = nullptr;
      delete file;
      file = nullptr;
      delete out;
      out = nullptr;
      Serial.println("Playback finished");
    }
  }
}