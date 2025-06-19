import sys
import os
import cv2  # Импортируем OpenCV для работы с изображениями
import numpy as np  # Импортируем NumPy, так как OpenCV использует массивы NumPy
# import pyvirtualcam # Больше не нужен для отправки кадров напрямую в камеру
import queue  # Импортируем модуль queue для создания очереди кадров
from PIL import Image, ImageSequence  # Для работы с GIF и PNG
import asyncio  # Импортируем asyncio для await
import threading  # Импортируем threading для использования Lock
import time  # Для time.time() и time.perf_counter() - измерения времени
import math  # Для math.sin() - для плавности анимации

import mmap  # Для работы с общей памятью
import struct  # Для упаковки/распаковки структуры данных в общей памяти
import win32event  # Для работы с Win32 событиями
import win32file  # Для работы с файловыми отображениями (memory-mapped files)
import win32api  # Для получения системных ошибок
import pywintypes  # Для обработки ошибок Win32 API

# Импортируем config_manager
import config_manager

# Импортируем POLLING_INTERVAL_SECONDS из reactive_monitor (если используется для asyncio.sleep)
# Предполагается, что reactive_monitor также импортируется в других местах, и POLLING_INTERVAL_SECONDS нужен.
try:
    from reactive_monitor import POLLING_INTERVAL_SECONDS
except ImportError:
    # Заглушка, если reactive_monitor или POLLING_INTERVAL_SECONDS недоступны
    POLLING_INTERVAL_SECONDS = 0.05
    print(
        "ПРЕДУПРЕЖДЕНИЕ: Не удалось импортировать POLLING_INTERVAL_SECONDS из reactive_monitor. Использовано значение по умолчанию (0.05).")

# --- КОНФИГУРАЦИЯ ПУТЕЙ ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Папка для всех обработанных аватаров и статических изображений (фона, оверлеев)
# Это папка, с которой работает пользователь.
AVATAR_ASSETS_FOLDER = os.path.join(SCRIPT_DIR, "reactive_avatar")

# Глобальные переменные для размеров и FPS камеры (размеры будут определены динамически размерами BG.png/gif)
CAM_WIDTH = 0
CAM_HEIGHT = 0
# CAM_FPS будет установлен из конфига, по умолчанию 60
CAM_FPS = 60  # Стандартное значение CAM_FPS перед загрузкой конфига
_initial_cam_fps_default = 60  # Значение по умолчанию, если в конфиге не найдено

# Глобальный объект для виртуальной камеры
# virtual_cam_obj = None # Больше не объект pyvirtualcam, а флаг состояния
virtual_cam_obj = False  # Флаг: True = камера инициализирована и работает, False = не инициализирована/ошибка

# Глобальные переменные для общей памяти и событий Win32
SHARED_MEM_NAME = "LunasVirtualCamSharedMemory"
NEW_FRAME_EVENT_NAME = "LunasVirtualCamNewFrameEvent"
MAX_BUFFER_SIZE = 1920 * 1080 * 3  # Максимальный размер буфера 1080p RGB24
# Формат структуры SharedVideoBuffer: uint32_t (width, height, fps, format, frameSize, frameReady)
# Little-endian, 6 unsigned ints
SHARED_BUFFER_HEADER_FORMAT = "<IIIIII"  # 6 unsigned integers
SHARED_BUFFER_HEADER_SIZE = struct.calcsize(SHARED_BUFFER_HEADER_FORMAT)
TOTAL_SHARED_MEM_SIZE = SHARED_BUFFER_HEADER_SIZE + MAX_BUFFER_SIZE

_shared_memory_map = None
_shared_memory_buffer = None
_new_frame_event = None

# Глобальная переменная для слушателя событий изменения статуса.
# Сюда можно присвоить функцию, которая будет вызываться при изменении статуса.
_status_change_listener = None

# Глобальная очередь для кадров, предназначенных для отображения в GUI
# Используем maxsize=1, чтобы всегда хранить только самый последний кадр
display_queue = queue.Queue(maxsize=1)

# Глобальное хранилище для всех анимированных ассетов (фон и аватары)
# Структура: "ключ_статуса" -> {"frames": [...], "original_fps": X, "current_float_index": 0.0, "animation_start_time": 0.0, "last_frame_time": 0.0, "smoothed_dt": 0.0, "durations": [...], "current_frame_index": 0, "frame_elapsed": 0.0}
_animation_assets = {}

# Коэффициент EMA сглаживания
ALPHA = 0.1

_last_composed_frame = None
_last_bg_index = -1
_last_avatar_index = -1

# Индексы текущих кадров для анимации
# _current_avatar_frame_index теперь не используется явно для индексации
# _current_background_frame_index теперь не используется явно для индексации

# Текущий активный набор кадров аватара (устанавливается voice_status_callback)
# Это будет ссылка на один из словарей в _animation_assets
_current_active_avatar_frames = {}
# Добавляем блокировку для потокобезопасного доступа к _current_active_avatar_frames
_avatar_frames_lock = threading.Lock()

# Флаг для управления циклом отправки кадров
_cam_loop_running = False

# Глобальная переменная для флага BOUNCING_ENABLED (из конфига)
_bouncing_enabled = False

BOUNCING_MAX_OFFSET_PIXELS = 10  # Максимальное смещение вверх в пикселях (magnitude)

# Глобальные переменные для анимации подпрыгивания
_bouncing_active = False  # Флаг, активна ли сейчас анимация подпрыгивания
_bouncing_start_time = 0.0  # Время начала анимации
BOUNCING_DURATION_MS = 150  # Длительность анимации в миллисекундах (0.15 секунды)

# Глобальные переменные для кроссфейда
_cross_fade_enabled = False  # Флаг, включен ли кроссфейд
_cross_fade_active = False  # Флаг, активен ли кроссфейд
_cross_fade_start_time = 0.0  # Время начала кроссфейда
# _old_avatar_frames_data теперь будет полным словарем: {"frames": [...], "original_fps": X, "current_float_index": Y}
_old_avatar_frames_data = {"frames": [], "original_fps": 1.0, "current_float_index": 0.0, "animation_start_time": 0.0,
                           "last_frame_time": 0.0, "smoothed_dt": 0.0, "durations": [], "current_frame_index": 0,
                           "frame_elapsed": 0.0}
_initial_cross_fade_duration_default = 200  # Значение по умолчанию для длительности кроссфейда
CROSS_FADE_DURATION_MS = _initial_cross_fade_duration_default  # Длительность кроссфейда в миллисекундах

# Новая глобальная переменная для управления сбросом анимации
_reset_animation_on_status_change = True  # По умолчанию сбрасывать

# Новая глобальная переменная для мгновенного перехода в статус "Говорит"
_instant_talk_transition = True  # По умолчанию мгновенный переход в статус "Говорит"

# Новые глобальные переменные для затемнения
_dim_enabled = True  # По умолчанию затемнение включено
DIM_PERCENTAGE = 50  # По умолчанию затемнение на 50%

# Добавляем переменную для отслеживания последнего известного статуса голоса
_last_known_voice_status = None

# New global flag to signal GUI that camera parameters changed and it needs restart
_camera_needs_restart = False

# Карта статусов на базовые имена файлов в AVATAR_ASSETS_FOLDER (без расширения)
STATUS_TO_FILENAME_MAP = {
    "Говорит": "Speaking",
    "Молчит": "Inactive",
    "Микрофон выключен (muted)": "Muted",
    "Полностью заглушен (deafened)": "Deafened",
    "Картинка загружается (или не определена)": "Inactive",  # Использовать неактивное для загрузки
    "Ошибка": "Inactive",  # Использовать неактивное для ошибки
    "Элемент статуса голоса не найден.": "Inactive"  # Использовать неактивное
}

# Базовое имя для фонового изображения
BACKGROUND_IMAGE_PATH = "BG"

CHECK_TIME = True

# --- ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ДЛЯ ОТОБРАЖЕНИЯ FPS ---
_fps_history = []  # Список для хранения истории FPS
_fps_display_frame_count = 0  # Счетчик кадров для обновления отображения FPS
_last_displayed_avg_fps = 0.0  # Последнее отображенное значение среднего FPS
FPS_DISPLAY_UPDATE_INTERVAL = 30  # Обновлять отображение FPS каждые N кадров
_send_time_ms = 0.0  # Время передачи в общую память и сигнализации SetEvent


def set_status_callback(callback_func):
    """Устанавливает функцию обратного вызова для обновления статуса."""
    global _status_change_listener
    _status_change_listener = callback_func


def _load_frames_from_file(base_name: str, is_avatar: bool = False, resize_to_cam: bool = False) -> tuple[
    list[np.ndarray], float, list[float]]:
    """
    Загружает кадры из GIF или PNG файла.
    Пытается загрузить GIF, если не найдет, то PNG.
    Возвращает список NumPy массивов (RGBA для аватаров, RGB для фона), оригинальный FPS и список длительностей кадров.
    Если это фоновое изображение, устанавливает глобальные CAM_WIDTH и CAM_HEIGHT.
    """
    global CAM_WIDTH, CAM_HEIGHT

    gif_path = os.path.join(AVATAR_ASSETS_FOLDER, f"{base_name}.gif")
    png_path = os.path.join(AVATAR_ASSETS_FOLDER, f"{base_name}.png")
    frames = []
    original_fps = 1.0  # Дефолтное значение для PNG или неизвестного GIF
    frame_durations = []  # Список длительностей каждого кадра в секундах

    file_to_load = None
    if os.path.exists(gif_path):
        file_to_load = gif_path
    elif os.path.exists(png_path):
        file_to_load = png_path
    else:
        print(
            f"  ПРЕДУПРЕЖДЕНИЕ: Ни GIF, ни PNG файл не найден для '{base_name}'. Возвращаю пустой список кадров, дефолтный FPS ({original_fps}) и пустые длительности кадров.")
        return [], original_fps, []

    try:
        with Image.open(file_to_load) as im:
            # Устанавливаем CAM_WIDTH и CAM_HEIGHT на основе первого кадра фона
            if base_name == BACKGROUND_IMAGE_PATH:
                CAM_WIDTH = im.width
                CAM_HEIGHT = im.height
                print(f"  Разрешение камеры установлено по фоновому изображению: {CAM_WIDTH}x{CAM_HEIGHT}")

            if file_to_load.endswith(".gif"):
                for frame in ImageSequence.Iterator(im):
                    frames.append(np.array(frame.convert("RGBA" if is_avatar else "RGB")))
                    # Сохраняем длительность каждого кадра в секундах
                    frame_durations.append(frame.info.get("duration", 100) / 1000.0)

                # Пытаемся получить duration из GIF и рассчитать FPS
                if 'duration' in im.info and im.info['duration'] > 0:
                    original_fps = 1000.0 / im.info['duration']
                else:
                    # Если duration не определен, используем разумное значение по умолчанию для GIF
                    original_fps = 15.0
                    print(
                        f"  ПРЕДУПРЕЖДЕНИЕ: Не удалось определить точный FPS для GIF '{base_name}'. Использую значение по умолчанию ({original_fps:.2f}).")

            else:  # PNG (статичное изображение)
                frames.append(np.array(im.convert("RGBA" if is_avatar else "RGB")))
                original_fps = 1.0  # Статичные изображения имеют 1 FPS
                if original_fps > 0:
                    frame_durations.append(1.0 / original_fps)  # Для PNG длительность кадра - 1/FPS
                else:
                    frame_durations.append(0.1)  # Fallback to 0.1s if FPS is 0

    except Exception as e:
        print(f"  ОШИБКА: Не удалось загрузить кадры из '{file_to_load}': {e}")
        return [], original_fps, []

    return frames, original_fps, frame_durations


def initialize_virtual_camera():
    """
    Инициализирует объект виртуальной камеры pyvirtualcam и предварительно загружает все изображения.
    Размеры камеры теперь определяются размерами фонового изображения BG.png/gif.
    Эта функция предназначена для вызова из gui_elements.py.
    """
    global virtual_cam_obj, CAM_WIDTH, CAM_HEIGHT, CAM_FPS
    global _animation_assets, _current_active_avatar_frames, _avatar_frames_lock, _old_avatar_frames_data
    global _bouncing_enabled, _cross_fade_enabled, CROSS_FADE_DURATION_MS, _reset_animation_on_status_change, _instant_talk_transition
    global _dim_enabled, DIM_PERCENTAGE
    global _shared_memory_map, _shared_memory_buffer, _new_frame_event

    # Закрываем существующие ресурсы общей памяти и события, если они активны
    if _shared_memory_map is not None:
        print("Общая память уже активна. Закрываю перед повторной инициализации.")
        shutdown_virtual_camera()

    print("\n--- Инициализация виртуальной камеры и предварительная загрузка изображений/анимаций ---")

    config = config_manager.load_config()  # Всегда загружаем последнюю конфигурацию

    # Обновляем все глобальные переменные из конфига
    _bouncing_enabled = config.get('BOUNCING_ENABLED', 'True').lower() == 'true'
    _cross_fade_enabled = config.get('CROSS_FADE_ENABLED', 'True').lower() == 'true'
    _reset_animation_on_status_change = config.get('RESET_ANIMATION_ON_STATUS_CHANGE', 'True').lower() == 'true'
    _instant_talk_transition = config.get('INSTANT_TALK_TRANSITION', 'True').lower() == 'true'
    _dim_enabled = config.get('DIM_ENABLED', 'True').lower() == 'true'

    try:
        dim_percentage_from_config = int(config.get('DIM_PERCENTAGE', '50'))
        DIM_PERCENTAGE = dim_percentage_from_config if 0 <= dim_percentage_from_config <= 100 else 50
    except ValueError:
        DIM_PERCENTAGE = 50

    # CAM_FPS из конфига теперь будет использоваться как максимальный предел для FPS камеры
    CAM_FPS_config_limit = _initial_cam_fps_default
    try:
        CAM_FPS_from_config = int(config.get('CAM_FPS', str(_initial_cam_fps_default)))
        CAM_FPS_config_limit = CAM_FPS_from_config if CAM_FPS_from_config > 0 else _initial_cam_fps_default
    except ValueError:
        pass  # Используем дефолтное значение

    # Загружаем фон и аватары первыми.
    # CAM_WIDTH и CAM_HEIGHT будут установлены функцией _load_frames_from_file при загрузке BG.
    bg_frames, bg_fps, bg_durations = _load_frames_from_file(BACKGROUND_IMAGE_PATH, is_avatar=False, resize_to_cam=True)
    _animation_assets["Background"] = {
        "frames": bg_frames,
        "original_fps": bg_fps,
        "current_float_index": 0.0,
        "animation_start_time": time.perf_counter(),
        "last_frame_time": time.perf_counter(),
        "smoothed_dt": 1.0 / CAM_FPS if CAM_FPS > 0 else POLLING_INTERVAL_SECONDS,  # Начальное сглаженное dt
        "durations": bg_durations,
        "current_frame_index": 0,  # Добавляем текущий индекс кадра для покадровой анимации
        "frame_elapsed": 0.0  # Добавляем время, прошедшее для текущего кадра
    }

    if not bg_frames:
        print("КРИТИЧЕСКАЯ ОШИБКА: Не удалось загрузить фоновое изображение. Не могу инициализировать камеру.")
        virtual_cam_obj = False  # Сигнал об ошибке запуска камеры
        return

    # Загружаем аватары и находим максимальный FPS среди всех ассетов
    max_effective_fps_found = bg_fps  # Начинаем с FPS фона
    for status, filename in STATUS_TO_FILENAME_MAP.items():
        frames, original_fps, frame_durations = _load_frames_from_file(filename, is_avatar=True)
        _animation_assets[status] = {
            "frames": frames,
            "original_fps": original_fps,
            "current_float_index": 0.0,
            "animation_start_time": time.perf_counter(),
            "last_frame_time": time.perf_counter(),
            "smoothed_dt": 1.0 / CAM_FPS if CAM_FPS > 0 else POLLING_INTERVAL_SECONDS,  # Начальное сглаженное dt
            "durations": frame_durations,
            "current_frame_index": 0,  # Добавляем текущий индекс кадра для покадровой анимации
            "frame_elapsed": 0.0  # Добавляем время, прошедшее для текущего кадра
        }
        if not frames:
            print(f"ПРЕДУПРЕЖДЕНИЕ: Не удалось загрузить аватар для статуса '{status}'. Использую пустой набор кадров.")

        # Обновляем максимальный FPS, если найден новый
        max_effective_fps_found = max(max_effective_fps_found, original_fps)

    # Проверка, что CAM_WIDTH и CAM_HEIGHT были установлены
    if CAM_WIDTH == 0 or CAM_HEIGHT == 0:
        print(
            "КРИТИЧЕСКАЯ ОШИБКА: Размеры камеры не были определены из фонового изображения. Использую стандартное разрешение 640x360.")
        CAM_WIDTH = 640
        CAM_HEIGHT = 360

    try:
        fade_duration_from_config = int(config.get('CROSS_FADE_DURATION_MS', str(_initial_cross_fade_duration_default)))
        CROSS_FADE_DURATION_MS = fade_duration_from_config if fade_duration_from_config >= 0 else _initial_cross_fade_duration_default
    except ValueError:
        CROSS_FADE_DURATION_MS = _initial_cross_fade_duration_default

    # Устанавливаем CAM_FPS, который будет использоваться для инициализации камеры,
    # как минимум из максимально найденного FPS и лимита из конфига.
    CAM_FPS = CAM_FPS_config_limit

    print(
        f"Итоговая частота кадров виртуальной камеры установлена на: {CAM_FPS} FPS.")

    try:
        print(f"Попытка открытия/создания общей памяти и события Win32: {CAM_WIDTH}x{CAM_HEIGHT} @ {CAM_FPS} FPS...")

        # Открытие/создание memory-mapped file
        try:
            _shared_memory_map = mmap.mmap(-1, TOTAL_SHARED_MEM_SIZE, tagname=SHARED_MEM_NAME)
            print(f"  Открыт существующий Memory-Mapped File: {SHARED_MEM_NAME}")
        except Exception as e:  # Catch any error, typically FileNotFoundError on first run
            print(f"  Не удалось открыть существующий Memory-Mapped File, попытка создания: {e}")
            _shared_memory_map = mmap.mmap(-1, TOTAL_SHARED_MEM_SIZE, tagname=SHARED_MEM_NAME, access=mmap.ACCESS_WRITE)
            print(f"  Создан новый Memory-Mapped File: {SHARED_MEM_NAME}")

        _shared_memory_buffer = memoryview(_shared_memory_map)

        # Открытие/создание Win32 Event
        try:
            _new_frame_event = win32event.OpenEvent(win32event.EVENT_ALL_ACCESS, False, NEW_FRAME_EVENT_NAME)
            print(f"  Открыто существующее Win32 Event: {NEW_FRAME_EVENT_NAME}")
        except pywintypes.error as e:
            if e.winerror == 2:  # ERROR_FILE_NOT_FOUND (Event not found)
                print(f"  Не удалось открыть существующее Win32 Event, попытка создания: {e}")
                _new_frame_event = win32event.CreateEvent(None, False, False, NEW_FRAME_EVENT_NAME)
                print(f"  Создано новое Win32 Event: {NEW_FRAME_EVENT_NAME}")
            else:
                raise e  # Перебрасываем другие ошибки Win32

        virtual_cam_obj = True  # Отмечаем, что инициализация прошла успешно

        # Записываем начальные параметры в общую память
        # Формат: width, height, fps, format (0=RGB24), frameSize, frameReady
        # frameSize будет обновляться при отправке каждого кадра,
        # frameReady устанавливается в 0 после использования в C++
        header_data = struct.pack(SHARED_BUFFER_HEADER_FORMAT,
                                  CAM_WIDTH, CAM_HEIGHT, CAM_FPS, 0,  # Format 0 for RGB24
                                  CAM_WIDTH * CAM_HEIGHT * 3,  # Initial frameSize
                                  0  # frameReady = 0, так как кадр еще не отправлен
                                  )
        _shared_memory_buffer[:SHARED_BUFFER_HEADER_SIZE] = header_data
        print("  Начальные параметры записаны в общую память.")

        initial_avatar_data = _animation_assets.get("Молчит",
                                                    {"frames": [], "original_fps": 1.0, "current_float_index": 0.0,
                                                     "animation_start_time": 0.0, "last_frame_time": 0.0,
                                                     "smoothed_dt": 0.0, "durations": [], "current_frame_index": 0,
                                                     "frame_elapsed": 0.0})
        _current_active_avatar_frames = initial_avatar_data
        # Инициализируем _old_avatar_frames_data пустой структурой
        _old_avatar_frames_data = {"frames": [], "original_fps": 1.0, "current_float_index": 0.0,
                                   "animation_start_time": 0.0, "last_frame_time": 0.0, "smoothed_dt": 0.0,
                                   "durations": [], "current_frame_index": 0, "frame_elapsed": 0.0}

        if not initial_avatar_data['frames']:
            # Создаем пустой черный RGBA кадр, если нет аватаров
            initial_avatar_data['frames'] = [np.zeros((CAM_HEIGHT, CAM_WIDTH, 4), dtype=np.uint8)]
            # Для заглушки используем оригинальный FPS или 1.0, если он не определен
            initial_avatar_data['durations'] = [1.0 / initial_avatar_data['original_fps']] if initial_avatar_data[
                                                                                                  'original_fps'] > 0 else [
                0.1]
            print("ПРЕДУПРЕЖДЕНИЕ: Нет кадров для 'Молчит' при инициализации. Использую заглушку.")

        # Композируем первый кадр для отправки
        initial_frame_rgb = _compose_frame(_animation_assets["Background"]["frames"][0],
                                           initial_avatar_data['frames'][0], y_offset_addition=0)

        # Отправляем первый кадр в общую память
        if initial_frame_rgb is not None:
            # Убедимся, что кадр в RGB24 (3 байта на пиксель) и правильного размера
            if initial_frame_rgb.shape[2] == 3 and initial_frame_rgb.shape[0] == CAM_HEIGHT and initial_frame_rgb.shape[
                1] == CAM_WIDTH:
                frame_data_bytes = initial_frame_rgb.tobytes()
                # Записываем данные кадра после заголовка
                _shared_memory_buffer[
                SHARED_BUFFER_HEADER_SIZE:SHARED_BUFFER_HEADER_SIZE + len(frame_data_bytes)] = frame_data_bytes

                # Обновляем frameReady в заголовке
                _shared_memory_buffer[SHARED_BUFFER_HEADER_SIZE - 4: SHARED_BUFFER_HEADER_SIZE] = struct.pack("<I",
                                                                                                              1)  # frameReady = 1

                # Сигнализируем событие
                win32event.SetEvent(_new_frame_event)
                print("  Первый кадр отправлен в общую память.")
            else:
                print("ОШИБКА: Неверный формат или размер первого кадра для общей памяти.")
        else:
            print("ОШИБКА: Композиция первого кадра вернула None.")

        try:
            while not display_queue.empty():  # Очищаем очередь перед помещением первого кадра
                display_queue.get_nowait()
            display_queue.put_nowait(initial_frame_rgb)
        except queue.Full:
            pass

        # Запускаем основной поток камеры (который теперь включает логику генерации)
        camera_loop = asyncio.new_event_loop()
        camera_thread = threading.Thread(target=run_camera_sending_loop_in_thread, args=(camera_loop,),
                                         name="CameraMainLoopThread")
        camera_thread.daemon = True  # Поток завершится при завершении основной программы
        camera_thread.start()
        print(f"Запущен основной поток камеры: {camera_thread.name}")


    except Exception as e:
        print(f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось инициализировать общую память/событие: {e}")
        print(
            "Пожалуйста, убедитесь, что у вас установлен 'pywin32' (`pip install pywin32`) и DLL виртуальной камеры зарегистрирована.")
        virtual_cam_obj = False  # Отмечаем, что инициализация не удалась


def update_camera_parameters():
    """
    Обновляет глобальные переменные виртуальной камеры и анимации из конфига.
    Эта функция НЕ создает и НЕ закрывает объект камеры pyvirtualcam.
    Она только обновляет глобальные переменные и устанавливает флаг _camera_needs_restart,
    если критические параметры (разрешение или FPS) изменились.
    Фактический перезапуск камеры (объекта pyvirtualcam) должен быть выполнен управляющим потоком (GUI).
    """
    global CAM_WIDTH, CAM_HEIGHT, CAM_FPS
    global _bouncing_enabled, _cross_fade_enabled, CROSS_FADE_DURATION_MS
    global _reset_animation_on_status_change, _instant_talk_transition
    global _dim_enabled, DIM_PERCENTAGE
    global _camera_needs_restart  # New flag
    global _animation_assets  # Добавлено для доступа к original_fps ассетов

    print("\n--- Обновление параметров виртуальной камеры в рантайме (только глобальные переменные) ---")

    old_cam_fps = CAM_FPS  # Сохраняем старый FPS для сравнения

    config = config_manager.load_config()

    # Update all global variables
    _bouncing_enabled = config.get('BOUNCING_ENABLED', 'True').lower() == 'true'
    _cross_fade_enabled = config.get('CROSS_FADE_ENABLED', 'True').lower() == 'true'
    _reset_animation_on_status_change = config.get('RESET_ANIMATION_ON_STATUS_CHANGE', 'True').lower() == 'true'
    _instant_talk_transition = config.get('INSTANT_TALK_TRANSITION', 'True').lower() == 'true'
    _dim_enabled = config.get('DIM_ENABLED', 'True').lower() == 'true'

    try:
        dim_percentage_from_config = int(config.get('DIM_PERCENTAGE', '50'))
        DIM_PERCENTAGE = dim_percentage_from_config if 0 <= dim_percentage_from_config <= 100 else 50
    except ValueError:
        DIM_PERCENTAGE = 50

    try:
        CAM_FPS_from_config = int(config.get('CAM_FPS', str(_initial_cam_fps_default)))
        if CAM_FPS_from_config != old_cam_fps:
            _camera_needs_restart = True
            print(
                f"Параметры камеры (FPS) изменились. Сигнализирую GUI о необходимости перезапуска камеры. (Было: {old_cam_fps}, Станет: {CAM_FPS_from_config})")
            CAM_FPS = CAM_FPS_from_config # Обновляем CAM_FPS, чтобы отразить новое значение
        else:
            _camera_needs_restart = False  # Если лимит из конфига не меняет финальный CAM_FPS

    except ValueError:
        _camera_needs_restart = False  # Если конфиг FPS невалиден

    # CAM_WIDTH и CAM_HEIGHT не обновляются здесь из конфига, они устанавливаются initialize_virtual_camera
    # на основе фонового изображения.
    print(f"  Разрешение камеры остается: {CAM_WIDTH}x{CAM_HEIGHT}")

    try:
        fade_duration_from_config = int(config.get('CROSS_FADE_DURATION_MS', str(_initial_cross_fade_duration_default)))
        CROSS_FADE_DURATION_MS = fade_duration_from_config if fade_duration_from_config >= 0 else _initial_cross_fade_duration_default
    except ValueError:
        CROSS_FADE_DURATION_MS = _initial_cross_fade_duration_default

    print("Параметры виртуальной камеры и настройки анимации успешно обновлены (только глобальные).")


def get_camera_needs_restart_flag():
    """Returns the flag indicating if camera needs restart."""
    global _camera_needs_restart
    return _camera_needs_restart


def reset_camera_needs_restart_flag():
    """Resets the flag indicating if camera needs restart."""
    global _camera_needs_restart
    _camera_needs_restart = False


def get_calculated_bg_16_9_resolution():
    """
    Возвращает текущие CAM_WIDTH и CAM_HEIGHT, которые теперь напрямую отражают размеры BG.
    Это заглушка, чтобы GUI не ломался при попытке получить 16:9 разрешение.
    """
    global CAM_WIDTH, CAM_HEIGHT
    return (CAM_WIDTH, CAM_HEIGHT)


def _compose_frame(background_frame_rgb: np.ndarray, avatar_rgba_image: np.ndarray | None,
                   y_offset_addition: int = 0) -> np.ndarray:
    """
    Композирует текущий кадр фона и заданное RGBA изображение аватара, применяя опциональное смещение по Y.
    Фон масштабируется точно до CAM_WIDTH и CAM_HEIGHT (без сохранения соотношения сторон).
    Возвращает NumPy массив RGB для отправки в виртуальную камеру.
    background_frame_rgb: RGB NumPy массив фонового кадра.
    avatar_rgba_image: RGBA NumPy массив изображения аватара, или None, если аватара нет.
    y_offset_addition: Дополнительное смещение по оси Y для аватара.
    """
    global CAM_WIDTH, CAM_HEIGHT

    if background_frame_rgb is None or CAM_WIDTH == 0 or CAM_HEIGHT == 0:
        return np.zeros((CAM_HEIGHT, CAM_WIDTH, 3), dtype=np.uint8)

    # Непосредственное масштабирование фона до размеров камеры.
    # Это приведет к растягиванию или сжатию, если соотношение сторон фона не совпадает с CAM_WIDTH/CAM_HEIGHT.
    output_frame = cv2.resize(background_frame_rgb, (CAM_WIDTH, CAM_HEIGHT), interpolation=cv2.INTER_LINEAR)

    # Остальная логика наложения аватара остается прежней
    if avatar_rgba_image is None or avatar_rgba_image.shape[0] == 0 or avatar_rgba_image.shape[1] == 0:
        return output_frame

    avatar_height, avatar_width, _ = avatar_rgba_image.shape

    new_avatar_w = int(avatar_width)
    new_avatar_h = int(avatar_height)

    if new_avatar_w <= 0 or new_avatar_h <= 0:
        return output_frame

    # Используем cv2.INTER_LINEAR для масштабирования аватара
    avatar_resized = cv2.resize(avatar_rgba_image, (new_avatar_w, new_avatar_h), interpolation=cv2.INTER_LINEAR)

    # Центрируем аватар относительно CAM_WIDTH/CAM_HEIGHT
    x_offset = (CAM_WIDTH - new_avatar_w) // 2
    # Смещаем аватар ниже, если масштабирован и включено подпрыгивание
    total_bounce_range = BOUNCING_MAX_OFFSET_PIXELS if _bouncing_enabled else 0
    y_offset = CAM_HEIGHT - new_avatar_h + total_bounce_range + y_offset_addition

    avatar_rgb_float = avatar_resized[:, :, :3].astype(np.float32)
    alpha_channel_float = avatar_resized[:, :, 3].astype(np.float32) / 255.0
    alpha_factor_3_chan = cv2.merge([alpha_channel_float, alpha_channel_float, alpha_channel_float])

    y1, y2 = y_offset, y_offset + new_avatar_h
    x1, x2 = x_offset, x_offset + new_avatar_w

    y2_clip = min(y2, CAM_HEIGHT)
    x2_clip = min(x2, CAM_WIDTH)
    y1_clip = max(0, y1)
    x1_clip = max(0, x1)

    actual_h = y2_clip - y1_clip
    actual_w = x2_clip - x1_clip

    if actual_h <= 0 or actual_w <= 0:
        return output_frame

    avatar_rgb_clipped = avatar_rgb_float[
                         (y1_clip - y_offset):(y1_clip - y_offset) + actual_h,
                         (x1_clip - x_offset):(x1_clip - x_offset) + actual_w
                         ]
    alpha_factor_clipped = alpha_factor_3_chan[
                           (y1_clip - y_offset):(y1_clip - y_offset) + actual_h,
                           (x1_clip - x_offset):(x1_clip - x_offset) + actual_w
                           ]

    if avatar_rgb_clipped.shape[0] == 0 or avatar_rgb_clipped.shape[1] == 0:
        return output_frame

    bg_roi = output_frame[y1_clip:y2_clip, x1_clip:x2_clip].astype(np.float32)

    blended_roi = avatar_rgb_clipped * alpha_factor_clipped + \
                  bg_roi * (1 - alpha_factor_clipped)

    output_frame[y1_clip:y2_clip, x1_clip:x2_clip] = blended_roi.astype(np.uint8)

    return output_frame


def get_static_preview_frame(current_status: str) -> np.ndarray:
    """
    Возвращает статичный кадр для предварительного просмотра в GUI,
    используя первый кадр фона и первый кадр текущего активного аватара.
    Принимает текущий статус для отображения соответствующего аватара.
    """
    global _animation_assets, CAM_WIDTH, CAM_HEIGHT

    # Используем CAM_WIDTH и CAM_HEIGHT, так как _compose_frame уже обработает масштабирование
    if "Background" not in _animation_assets or not _animation_assets["Background"][
        "frames"] or CAM_WIDTH == 0 or CAM_HEIGHT == 0:
        print(
            "ПРЕДУПРЕЖДЕНИЕ (get_static_preview_frame): Фон не загружен или размеры камеры не определены. Возвращаю пустой кадр.")
        return np.zeros((360, 640, 3), dtype=np.uint8)

    # Получаем данные фона из _animation_assets
    background_data_for_preview = _animation_assets["Background"]
    background_frames_for_preview = background_data_for_preview['frames']

    avatar_data_for_preview = _animation_assets.get(current_status,
                                                    {"frames": [], "original_fps": 1.0, "current_float_index": 0.0})
    avatar_frames_for_preview = avatar_data_for_preview['frames']

    if not avatar_frames_for_preview:
        fallback_data = _animation_assets.get("Молчит",
                                              {"frames": [], "original_fps": 1.0, "current_float_index": 0.0})
        fallback_frames = fallback_data['frames']
        print(
            f"ПРЕДУПРЕЖДЕНИЕ (get_static_preview_frame): Кадры для статуса '{current_status}' не найдены. Использую 'Молчит' ({len(fallback_frames)} кадров) для предпросмотра.")
        avatar_frames_for_preview = fallback_frames  # Use fallback if original is empty

    preview_frame = _compose_frame(background_frames_for_preview[0], avatar_frames_for_preview[0], y_offset_addition=0)
    return preview_frame


def run_camera_sending_loop_in_thread(loop):
    """Целевая функция для основного потока виртуальной камеры."""
    asyncio.set_event_loop(loop)
    loop.run_until_complete(start_frame_sending_loop())


async def start_frame_sending_loop():
    """
    Асинхронный цикл, который постоянно генерирует и отправляет кадры в виртуальную камеру.
    Эта функция предполагает, что виртуальная камера уже инициализирована (через общую память).
    """
    print(f"[{threading.current_thread().name}] Цикл отправки кадров запущен.")
    global _cam_loop_running, display_queue, virtual_cam_obj, _current_active_avatar_frames, _animation_assets, _avatar_frames_lock
    global _bouncing_enabled, BOUNCING_MAX_OFFSET_PIXELS, _bouncing_active, _bouncing_start_time, CAM_FPS
    global _cross_fade_active, _cross_fade_start_time, _old_avatar_frames_data, _cross_fade_enabled, CROSS_FADE_DURATION_MS
    global _dim_enabled, DIM_PERCENTAGE, _last_composed_frame, _last_known_voice_status
    global _shared_memory_buffer, _new_frame_event, SHARED_BUFFER_HEADER_SIZE, SHARED_BUFFER_HEADER_FORMAT
    global _fps_history, _fps_display_frame_count, _last_displayed_avg_fps, FPS_DISPLAY_UPDATE_INTERVAL
    global _send_time_ms
    global ALPHA  # Добавлено для использования в EMA

    _cam_loop_running = True

    while _cam_loop_running:
        real_frame_start = time.perf_counter()  # Начало измерения цикла кадра

        current_bounce_offset = 0

        now = time.perf_counter()  # Текущее время для расчетов elapsed

        # --- Логика расчета смещения для разового подпрыгивания ---
        if _bouncing_active and _bouncing_enabled:
            elapsed_ms = (now - _bouncing_start_time) * 1000
            if elapsed_ms >= BOUNCING_DURATION_MS:
                _bouncing_active = False
                current_bounce_offset = 0
            else:
                progress = elapsed_ms / BOUNCING_DURATION_MS
                current_bounce_offset = int(-BOUNCING_MAX_OFFSET_PIXELS * math.sin(progress * math.pi))

        try:
            # Если общая память/событие не активны, пауза и продолжение
            if _shared_memory_buffer is None or _new_frame_event is None:
                await asyncio.sleep(POLLING_INTERVAL_SECONDS)  # Пауза, чтобы не нагружать ЦПУ
                continue  # Продолжаем цикл, ожидая, что ресурсы могут быть инициализированы позже

            final_avatar_image_rgba = None

            with _avatar_frames_lock:
                # --- Обработка фонового кадра ---
                background_idx_to_use = 0
                if "Background" in _animation_assets and _animation_assets["Background"]["frames"]:
                    bg_data = _animation_assets["Background"]

                    # Логика покадрового продвижения для фона (если это GIF с duration)
                    if bg_data['durations'] and len(bg_data['frames']) > 0:
                        delta = now - bg_data['last_frame_time']
                        bg_data['frame_elapsed'] += delta
                        bg_data['last_frame_time'] = now

                        while bg_data['frame_elapsed'] >= bg_data['durations'][bg_data['current_frame_index']]:
                            bg_data['frame_elapsed'] -= bg_data['durations'][bg_data['current_frame_index']]
                            bg_data['current_frame_index'] = (bg_data['current_frame_index'] + 1) % len(
                                bg_data['durations'])
                        background_idx_to_use = bg_data['current_frame_index']
                    else:  # Если PNG или GIF без durations, используем старую логику (или просто первый кадр)
                        # Для PNG или GIF без durations, используем original_fps для продвижения
                        bg_elapsed = now - bg_data['last_frame_time']
                        bg_data['last_frame_time'] = now
                        bg_data['smoothed_dt'] = (1 - ALPHA) * bg_data['smoothed_dt'] + ALPHA * bg_elapsed
                        if bg_data['original_fps'] > 0:
                            bg_advance = bg_data['original_fps'] * bg_data['smoothed_dt']
                            bg_data['current_float_index'] = (bg_data['current_float_index'] + bg_advance) % len(
                                bg_data['frames'])
                        background_idx_to_use = int(bg_data['current_float_index']) % len(bg_data['frames'])

                    background_frame_to_composite = bg_data['frames'][background_idx_to_use]
                else:
                    print("ПРЕДУПРЕЖДЕНИЕ: Фон не загружен в _animation_assets. Используется черный кадр.")
                    background_frame_to_composite = np.zeros((CAM_HEIGHT, CAM_WIDTH, 3), dtype=np.uint8)

                # --- Обработка текущего аватара ---
                current_avatar_data = _current_active_avatar_frames
                current_avatar_frames_list = current_avatar_data.get('frames', [])

                if current_avatar_frames_list:
                    # Логика покадрового продвижения для аватара
                    if current_avatar_data['durations'] and len(current_avatar_frames_list) > 0:
                        delta = now - current_avatar_data['last_frame_time']
                        current_avatar_data['frame_elapsed'] += delta
                        current_avatar_data['last_frame_time'] = now

                        while current_avatar_data['frame_elapsed'] >= current_avatar_data['durations'][
                            current_avatar_data['current_frame_index']]:
                            current_avatar_data['frame_elapsed'] -= current_avatar_data['durations'][
                                current_avatar_data['current_frame_index']]
                            current_avatar_data['current_frame_index'] = (current_avatar_data[
                                                                              'current_frame_index'] + 1) % len(
                                current_avatar_data['durations'])
                        current_avatar_idx_to_use = current_avatar_data['current_frame_index']
                    else:  # Если PNG или GIF без durations, используем старую логику
                        current_avatar_elapsed = now - current_avatar_data['last_frame_time']
                        current_avatar_data['last_frame_time'] = now
                        current_avatar_data['smoothed_dt'] = (1 - ALPHA) * current_avatar_data[
                            'smoothed_dt'] + ALPHA * current_avatar_elapsed

                        if current_avatar_data['original_fps'] > 0:
                            current_avatar_advance = current_avatar_data['original_fps'] * current_avatar_data[
                                'smoothed_dt']
                            current_avatar_data['current_float_index'] = (current_avatar_data[
                                                                              'current_float_index'] + current_avatar_advance) % len(
                                current_avatar_frames_list)
                        current_avatar_idx_to_use = int(current_avatar_data['current_float_index']) % len(
                            current_avatar_frames_list)

                    current_avatar_rgba = current_avatar_frames_list[current_avatar_idx_to_use].copy()
                else:
                    current_avatar_rgba = np.zeros((CAM_HEIGHT, CAM_WIDTH, 4), dtype=np.uint8)

                # --- Обработка старого аватара (для кроссфейда) ---
                if _cross_fade_active and _cross_fade_enabled:
                    elapsed_ms_fade = (now - _cross_fade_start_time) * 1000
                    if elapsed_ms_fade >= CROSS_FADE_DURATION_MS:
                        _cross_fade_active = False
                        final_avatar_image_rgba = current_avatar_rgba
                        # Очищаем _old_avatar_frames_data после завершения кроссфейда
                        _old_avatar_frames_data = {"frames": [], "original_fps": 1.0, "current_float_index": 0.0,
                                                   "animation_start_time": 0.0, "last_frame_time": 0.0,
                                                   "smoothed_dt": 0.0, "durations": [], "current_frame_index": 0,
                                                   "frame_elapsed": 0.0}
                    else:
                        fade_progress = elapsed_ms_fade / CROSS_FADE_DURATION_MS
                        old_opacity = 1.0 - fade_progress
                        new_opacity = fade_progress

                        old_avatar_frames_list = _old_avatar_frames_data.get('frames', [])

                        old_avatar_rgba = np.zeros((CAM_HEIGHT, CAM_WIDTH, 4), dtype=np.uint8)
                        if old_avatar_frames_list:
                            # Логика покадрового продвижения для старого аватара
                            if _old_avatar_frames_data['durations'] and len(old_avatar_frames_list) > 0:
                                delta = now - _old_avatar_frames_data['last_frame_time']
                                _old_avatar_frames_data['frame_elapsed'] += delta
                                _old_avatar_frames_data['last_frame_time'] = now

                                while _old_avatar_frames_data['frame_elapsed'] >= _old_avatar_frames_data['durations'][
                                    _old_avatar_frames_data['current_frame_index']]:
                                    _old_avatar_frames_data['frame_elapsed'] -= _old_avatar_frames_data['durations'][
                                        _old_avatar_frames_data['current_frame_index']]
                                    _old_avatar_frames_data['current_frame_index'] = (_old_avatar_frames_data[
                                                                                          'current_frame_index'] + 1) % len(
                                        _old_avatar_frames_data['durations'])
                                old_avatar_idx_to_use = _old_avatar_frames_data['current_frame_index']
                            else:  # Если PNG или GIF без durations, используем старую логику
                                old_avatar_elapsed = now - _old_avatar_frames_data['last_frame_time']
                                _old_avatar_frames_data['last_frame_time'] = now
                                _old_avatar_frames_data['smoothed_dt'] = (1 - ALPHA) * _old_avatar_frames_data[
                                    'smoothed_dt'] + ALPHA * old_avatar_elapsed

                                if _old_avatar_frames_data['original_fps'] > 0:
                                    old_avatar_advance = _old_avatar_frames_data['original_fps'] * \
                                                         _old_avatar_frames_data['smoothed_dt']
                                    _old_avatar_frames_data['current_float_index'] = (_old_avatar_frames_data[
                                                                                          'current_float_index'] + old_avatar_advance) % len(
                                        old_avatar_frames_list)
                                old_avatar_idx_to_use = int(_old_avatar_frames_data['current_float_index']) % len(
                                    old_avatar_frames_list)

                            old_avatar_rgba = old_avatar_frames_list[old_avatar_idx_to_use].copy()

                        target_h, target_w = current_avatar_rgba.shape[0], current_avatar_rgba.shape[1]
                        if old_avatar_rgba.shape[:2] != (target_h, target_w):
                            old_avatar_rgba = cv2.resize(old_avatar_rgba, (target_w, target_h),
                                                         interpolation=cv2.INTER_AREA)

                        old_rgb_float = old_avatar_rgba[:, :, :3].astype(np.float32)
                        old_alpha_float = old_avatar_rgba[:, :, 3].astype(np.float32) / 255.0

                        new_rgb_float = current_avatar_rgba[:, :, :3].astype(np.float32)
                        new_alpha_float = current_avatar_rgba[:, :, 3].astype(np.float32) / 255.0

                        blended_alpha = old_alpha_float * old_opacity + new_alpha_float * new_opacity
                        blended_alpha = np.clip(blended_alpha, 0.0, 1.0)

                        blended_rgb = old_rgb_float * old_opacity + new_rgb_float * new_opacity

                        final_avatar_image_rgba = np.zeros((target_h, target_w, 4), dtype=np.uint8)
                        final_avatar_image_rgba[:, :, :3] = np.clip(blended_rgb, 0, 255).astype(np.uint8)
                        final_avatar_image_rgba[:, :, 3] = np.clip(blended_alpha * 255, 0, 255).astype(np.uint8)

                else:
                    final_avatar_image_rgba = current_avatar_rgba

            # --- Применение затемнения ---
            # Применяем затемнение, если оно включено и статус не "Говорит"
            if _dim_enabled and _last_known_voice_status != "Говорит" and final_avatar_image_rgba is not None:
                dim_factor = 1.0 - (DIM_PERCENTAGE / 100.0)
                # Применяем затемнение только к RGB каналам, альфа-канал оставляем неизменным
                final_avatar_image_rgba[:, :, :3] = (final_avatar_image_rgba[:, :, :3] * dim_factor).astype(np.uint8)

            composition_end_time = time.perf_counter()  # Время окончания композиции
            composed_frame_rgb = _compose_frame(background_frame_to_composite, final_avatar_image_rgba,
                                                y_offset_addition=current_bounce_offset)
            frame_gen_ms = (
                                   time.perf_counter() - composition_end_time) * 1000  # Время генерации текущего кадра (фактически, время выполнения _compose_frame)

            # --- Измерение времени отправки в общую память и сигнализации события ---
            start_send_time = time.perf_counter()

            # --- Отправка кадра в общую память ---
            if composed_frame_rgb is not None:
                # Убедимся, что кадр в RGB24 (3 байта на пиксель) и правильного размера
                if composed_frame_rgb.shape[2] == 3 and composed_frame_rgb.shape[0] == CAM_HEIGHT and \
                        composed_frame_rgb.shape[1] == CAM_WIDTH:
                    frame_data_bytes = composed_frame_rgb.tobytes()
                    # Записываем данные кадра после заголовка
                    _shared_memory_buffer[
                    SHARED_BUFFER_HEADER_SIZE:SHARED_BUFFER_HEADER_SIZE + len(frame_data_bytes)] = frame_data_bytes

                    # Обновляем frameReady в заголовке
                    # Сначала читаем текущий заголовок, чтобы не перезаписывать другие поля
                    current_header = struct.unpack(SHARED_BUFFER_HEADER_FORMAT,
                                                   _shared_memory_buffer[:SHARED_BUFFER_HEADER_SIZE])
                    updated_header = list(current_header)
                    updated_header[5] = 1  # frameReady = 1 (индекс 5)
                    _shared_memory_buffer[:SHARED_BUFFER_HEADER_SIZE] = struct.pack(SHARED_BUFFER_HEADER_FORMAT,
                                                                                    *updated_header)

                    # Сигнализируем событие
                    win32event.SetEvent(_new_frame_event)
                else:
                    print("ОШИБКА: Неверный формат или размер композированного кадра для общей памяти.")
            else:
                print("ПРЕДУПРЕЖДЕНИЕ: Композированный кадр для отправки оказался None. Отправляю черный кадр.")
                black_frame = np.zeros((CAM_HEIGHT, CAM_WIDTH, 3), dtype=np.uint8)
                frame_data_bytes = black_frame.tobytes()
                _shared_memory_buffer[
                SHARED_BUFFER_HEADER_SIZE:SHARED_BUFFER_HEADER_SIZE + len(frame_data_bytes)] = frame_data_bytes
                current_header = struct.unpack(SHARED_BUFFER_HEADER_FORMAT,
                                               _shared_memory_buffer[:SHARED_BUFFER_HEADER_SIZE])
                updated_header = list(current_header)
                updated_header[5] = 1  # frameReady = 1
                _shared_memory_buffer[:SHARED_BUFFER_HEADER_SIZE] = struct.pack(SHARED_BUFFER_HEADER_FORMAT,
                                                                                *updated_header)
                win32event.SetEvent(_new_frame_event)


            # Обновление очереди для GUI предпросмотра
            try:
                while not display_queue.empty():
                    display_queue.get_nowait()
                display_queue.put_nowait(composed_frame_rgb)
            except queue.Full:
                pass

        except Exception as e:
            print(f"ОШИБКА в цикле генерации кадров: {e}")
            await asyncio.sleep(POLLING_INTERVAL_SECONDS)  # Используем POLLING_INTERVAL_SECONDS

        # Добавляем задержку для поддержания FPS
        # Время, которое должно пройти для следующего кадра (в секундах)
        frame_time_target = 1.0 / CAM_FPS if CAM_FPS > 0 else POLLING_INTERVAL_SECONDS
        # Время, которое заняла вся итерация цикла до момента сна
        current_loop_duration = time.perf_counter() - real_frame_start  # Использование real_frame_start

        sleep_duration = frame_time_target - current_loop_duration
        if sleep_duration > 0:
            await asyncio.sleep(sleep_duration)
        else:
            await asyncio.sleep(0.001)  # Минимальная задержка, чтобы не нагружать ЦПУ
            # print(f"ПРЕДУПРЕЖДЕНИЕ: Не успеваем за FPS {CAM_FPS}. Пропуск задержки. (Заняло {current_loop_duration*1000:.2f} мс)")

        real_frame_end = time.perf_counter()  # Конец измерения цикла кадра
        real_frame_ms = (real_frame_end - real_frame_start) * 1000
        # print(f"[DEBUG] Цикл кадра занял: {real_frame_ms:.1f} мс")  # Отладочный вывод


def voice_status_callback(status_message: str, debug_message: str):
    """
    Эта функция вызывается при каждом изменении статуса голоса.
    Она обновляет набор кадров аватара для отображения и выводит статус в консоль.
    """
    global _current_active_avatar_frames
    global _status_change_listener, _animation_assets, _avatar_frames_lock
    global _bouncing_active, _bouncing_start_time, _bouncing_enabled, _last_known_voice_status
    global _cross_fade_active, _cross_fade_start_time, _old_avatar_frames_data, _cross_fade_enabled, CROSS_FADE_DURATION_MS
    global _reset_animation_on_status_change, _instant_talk_transition
    global CAM_FPS  # Для инициализации smoothed_dt

    if _status_change_listener:
        _status_change_listener(status_message, debug_message)

    with _avatar_frames_lock:
        # Получаем шаблон данных для нового активного аватара
        new_active_avatar_data_template = _animation_assets.get(status_message,
                                                                {"frames": [], "original_fps": 1.0,
                                                                 "current_float_index": 0.0,
                                                                 "animation_start_time": 0.0, "last_frame_time": 0.0,
                                                                 "smoothed_dt": 0.0, "durations": [],
                                                                 "current_frame_index": 0, "frame_elapsed": 0.0})
        # Если для нового статуса нет кадров, используем запасной вариант 'Молчит'
        if not new_active_avatar_data_template['frames']:
            fallback_data = _animation_assets.get("Молчит",
                                                  {"frames": [], "original_fps": 1.0, "current_float_index": 0.0,
                                                   "animation_start_time": 0.0, "last_frame_time": 0.0,
                                                   "smoothed_dt": 0.0, "durations": [], "current_frame_index": 0,
                                                   "frame_elapsed": 0.0})
            if not fallback_data['frames']:  # Если и 'Молчит' не найден, создаем пустую заглушку
                fallback_data['frames'] = [np.zeros((CAM_HEIGHT, CAM_WIDTH, 4), dtype=np.uint8)]
                fallback_data['durations'] = [0.1]  # Default duration for empty frame

            # Только если запасной вариант - это другой ассет
            if fallback_data is not new_active_avatar_data_template:
                print(
                    f"ПРЕДУПРЕЖДЕНИЕ (voice_status_callback): Кадры для статуса '{status_message}' не найдены. Использую запасной вариант 'Молчит'.")
                new_active_avatar_data_template = fallback_data
            else:
                print(
                    f"ПРЕДУПРЕЖДЕНИЕ (voice_status_callback): Кадры для статуса '{status_message}' не найдены. Уже использую 'Молчит'.")

        # Сравниваем объекты, чтобы определить, действительно ли это новый набор кадров
        if new_active_avatar_data_template is not _current_active_avatar_frames:
            # Логика для INSTANT_TALK_TRANSITION: если включен и статус "Говорит"
            if _instant_talk_transition and status_message == "Говорит":
                _cross_fade_active = False  # Отключаем кроссфейд для этого перехода
                # Очищаем старые данные для чистого появления
                _old_avatar_frames_data = {"frames": [], "original_fps": 1.0, "current_float_index": 0.0,
                                           "animation_start_time": 0.0, "last_frame_time": 0.0, "smoothed_dt": 0.0,
                                           "durations": [], "current_frame_index": 0, "frame_elapsed": 0.0}
            elif _cross_fade_enabled:  # Если INSTANT_TALK_TRANSITION не активен или не статус "Говорит", и кроссфейд включен
                # Копируем текущее состояние активного аватара в старые данные для кроссфейда
                _old_avatar_frames_data = _current_active_avatar_frames.copy()
                _cross_fade_active = True
                _cross_fade_start_time = time.perf_counter()  # Используем perf_counter()
                # Важно: Сбрасываем last_frame_time и animation_start_time для старого аватара,
                # чтобы его анимация начиналась корректно с момента начала кроссфейда.
                _old_avatar_frames_data['last_frame_time'] = time.perf_counter()
                _old_avatar_frames_data['animation_start_time'] = time.perf_counter()
                _old_avatar_frames_data[
                    'smoothed_dt'] = 1.0 / CAM_FPS if CAM_FPS > 0 else POLLING_INTERVAL_SECONDS  # Re-initialize smoothed_dt
                _old_avatar_frames_data['current_frame_index'] = _current_active_avatar_frames.get(
                    'current_frame_index', 0)
                _old_avatar_frames_data['frame_elapsed'] = _current_active_avatar_frames.get('frame_elapsed', 0.0)
            else:  # Если кроссфейд выключен
                _cross_fade_active = False
                # Очищаем старые данные
                _old_avatar_frames_data = {"frames": [], "original_fps": 1.0, "current_float_index": 0.0,
                                           "animation_start_time": 0.0, "last_frame_time": 0.0, "smoothed_dt": 0.0,
                                           "durations": [], "current_frame_index": 0, "frame_elapsed": 0.0}

            # Обновляем _current_active_avatar_frames ссылкой на данные из _animation_assets
            _current_active_avatar_frames = new_active_avatar_data_template

            # Применяем логику сброса/продолжения анимации для НОВОГО активного аватара
            # Если это мгновенный переход на "Говорит" или сброс включен, сбрасываем индекс и таймеры
            if (_instant_talk_transition and status_message == "Говорит") or _reset_animation_on_status_change:
                _current_active_avatar_frames['current_float_index'] = 0.0
                _current_active_avatar_frames['animation_start_time'] = time.perf_counter()
                _current_active_avatar_frames['last_frame_time'] = time.perf_counter()
                _current_active_avatar_frames[
                    'smoothed_dt'] = 1.0 / CAM_FPS if CAM_FPS > 0 else POLLING_INTERVAL_SECONDS
                _current_active_avatar_frames['current_frame_index'] = 0  # Сбрасываем покадровый индекс
                _current_active_avatar_frames['frame_elapsed'] = 0.0  # Сбрасываем прошедшее время для кадра
            # else: если RESET_ANIMATION_ON_STATUS_CHANGE False,
            # new_active_avatar_data['current_float_index'] и smoothed_dt для этого статуса сохраняют свои предыдущие значения.

            # Если после всех проверок кадры все еще пусты, выводим критическое предупреждение
            if not _current_active_avatar_frames['frames']:
                print(
                    "КРИТИЧЕСКОЕ ПРЕДУПРЕЖДЕНИЕ: Нет доступных кадров ни для текущего статуса, ни для 'Молчит'. Анимация аватара будет пустой.")

        # --- Логика запуска анимации подпрыгивания ---
        if (status_message == "Говорит" and
                _bouncing_enabled and
                not _bouncing_active):

            if _last_known_voice_status != "Говорит":
                _bouncing_active = True
                _bouncing_start_time = time.perf_counter()  # Используем perf_counter()

        _last_known_voice_status = status_message


def shutdown_virtual_camera():
    """Закрывает общую память и Win32 Event."""
    print("Запрос на завершение виртуальной камеры (освобождение общей памяти)...")
    global virtual_cam_obj, _cam_loop_running, _shared_memory_map, _shared_memory_buffer, _new_frame_event

    _cam_loop_running = False  # Это приведет к завершению цикла asyncio в потоке

    if _shared_memory_map is not None:
        print("  Закрытие общей памяти...")
        try:
            _shared_memory_map.close()
            _shared_memory_map = None
            _shared_memory_buffer = None
            print("  Общая память закрыта.")
        except Exception as e:
            print(f"  Ошибка при закрытии общей памяти: {e}")
            _shared_memory_map = None
            _shared_memory_buffer = None  # Ensure it's None even if close fails

    if _new_frame_event is not None:
        print("  Закрытие Win32 Event...")
        try:
            win32api.CloseHandle(_new_frame_event)
            _new_frame_event = None
            print("  Win32 Event закрыт.")
        except Exception as e:
            print(f"  Ошибка при закрытии Win32 Event: {e}")
            _new_frame_event = None  # Ensure it's None even if close fails

    virtual_cam_obj = False  # Mark camera as shut down
    print("Виртуальная камера (ресурсы общей памяти) завершена.")


# Этот блок будет выполнен только при прямом запуске virtual_camera.py,
# а не при импорте.
if __name__ == '__main__':
    print("Запуск virtual_camera.py напрямую для тестирования...")
    # Для базового тестирования:
    # 1. Убедитесь, что DLL зарегистрирована.
    # 2. Убедитесь, что в папке 'reactive_avatar' есть BG.png/gif и Inactive.png/gif (или Speaking.png/gif).
    # 3. Запустите этот скрипт.
    # 4. Откройте Discord/OBS и выберите LunasVirtualCam.
    # 5. Вы увидите изображение.
    # 6. Нажмите Enter, чтобы завершить.

    initialize_virtual_camera()
    if virtual_cam_obj is False:
        print("Инициализация камеры завершилась ошибкой. Выход.")
        sys.exit(1)

    print("\nВиртуальная камера запущена. Проверьте в Discord/OBS. Нажмите Enter для завершения...")
    try:
        input()
    except KeyboardInterrupt:
        pass
    finally:
        shutdown_virtual_camera()
        print("Тестирование завершено.")