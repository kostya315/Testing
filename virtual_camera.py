import sys
import os
import cv2  # Импортируем OpenCV для работы с изображениями
import numpy as np  # Импортируем NumPy, так как OpenCV использует массивы NumPy
import pyvirtualcam  # Импортируем библиотеку для создания виртуальной камеры
import queue  # Импортируем модуль queue для создания очереди кадров
from PIL import Image, ImageSequence  # Для работы с GIF и PNG
import asyncio  # Импортируем asyncio для await
import threading  # Импортируем threading для использования Lock
import time  # Для time.time() - измерения времени
import math  # Для math.sin() - для плавности анимации

# Импортируем config_manager
import config_manager
# Импортируем POLLING_INTERVAL_SECONDS из reactive_monitor (если используется для asyncio.sleep)
# Предполагается, что reactive_monitor также импортируется в других местах, и POLLING_INTERVAL_SECONDS нужен.
try:
    from reactive_monitor import POLLING_INTERVAL_SECONDS
except ImportError:
    # Заглушка, если reactive_monitor или POLLING_INTERVAL_SECONDS недоступны
    POLLING_INTERVAL_SECONDS = 0.05
    print("ПРЕДУПРЕЖДЕНИЕ: Не удалось импортировать POLLING_INTERVAL_SECONDS из reactive_monitor. Использовано значение по умолчанию (0.05).")


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
virtual_cam_obj = None

# Глобальная переменная для слушателя событий изменения статуса.
# Сюда можно присвоить функцию, которая будет вызываться при изменении статуса.
_status_change_listener = None

# Глобальная очередь для кадров, предназначенных для отображения в GUI
# Используем maxsize=1, чтобы всегда хранить только самый последний кадр
display_queue = queue.Queue(maxsize=1)

# Глобальные переменные для хранения загруженных кадров
_background_frames_list = []  # Список NumPy массивов (RGB) для фоновых кадров
_original_background_fps = CAM_FPS  # Оригинальный FPS фона
# _avatar_frames_map теперь будет хранить словари: "статус" -> {"frames": [...], "original_fps": X, "current_float_index": 0.0}
_avatar_frames_map = {}
_last_composed_frame = None
_last_bg_index = -1
_last_avatar_index = -1

# Индексы текущих кадров для анимации (теперь будут храниться внутри _avatar_frames_map)
_current_avatar_frame_index = 0  # Сохраняется для совместимости/отладки
# _current_avatar_frame_float_index теперь будет храниться в _current_active_avatar_frames['current_float_index']
_current_background_frame_index = 0  # Целочисленный индекс (для совместимости, основной - float)
_current_background_frame_float_index = 0.0  # Плавающий индекс для точного воспроизведения GIF фона

# Текущий активный набор кадров аватара (устанавливается voice_status_callback)
# Теперь это будет словарь: {"frames": [...], "original_fps": X, "current_float_index": 0.0}
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
_old_avatar_frames_data = {"frames": [], "original_fps": 1.0, "current_float_index": 0.0}
# _old_avatar_fade_float_index теперь будет храниться в _old_avatar_frames_data['current_float_index']
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

def set_status_callback(callback_func):
    """Устанавливает функцию обратного вызова для обновления статуса."""
    global _status_change_listener
    _status_change_listener = callback_func


def _load_frames_from_file(base_name: str, is_avatar: bool = False, resize_to_cam: bool = False) -> tuple[list[np.ndarray], float]:
    """
    Загружает кадры из GIF или PNG файла.
    Пытается загрузить GIF, если не найдет, то PNG.
    Возвращает список NumPy массивов (RGBA для аватаров, RGB для фона) и оригинальный FPS.
    Если это фоновое изображение, устанавливает глобальные CAM_WIDTH и CAM_HEIGHT.
    """
    global CAM_WIDTH, CAM_HEIGHT

    gif_path = os.path.join(AVATAR_ASSETS_FOLDER, f"{base_name}.gif")
    png_path = os.path.join(AVATAR_ASSETS_FOLDER, f"{base_name}.png")
    frames = []
    original_fps = 30.0  # Временное дефолтное значение для загрузки

    if 'CAM_FPS' in globals() and isinstance(CAM_FPS, (int, float)) and CAM_FPS > 0:
        original_fps = float(CAM_FPS)

    file_to_load = None
    if os.path.exists(gif_path):
        file_to_load = gif_path
    elif os.path.exists(png_path):
        file_to_load = png_path
    else:
        print(
            f"  ПРЕДУПРЕЖДЕНИЕ: Ни GIF, ни PNG файл не найден для '{base_name}'. Возвращаю пустой список кадров и дефолтный FPS ({original_fps}).")
        return [], original_fps

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

                if 'duration' in im.info and im.info['duration'] > 0:
                    original_fps = 1000.0 / im.info['duration']
                elif frames:
                    print(
                        f"  ПРЕДУПРЕЖДЕНИЕ: Не удалось определить точный FPS для GIF '{base_name}'. Использую дефолтный FPS ({original_fps:.2f}).")
                else:
                    original_fps = 1.0

            else:  # PNG (статичное изображение)
                frames.append(np.array(im.convert("RGBA" if is_avatar else "RGB")))
                original_fps = 1.0

    except Exception as e:
        print(f"  ОШИБКА: Не удалось загрузить кадры из '{file_to_load}': {e}")
        return [], original_fps

    return frames, original_fps


def initialize_virtual_camera():
    """
    Инициализирует объект виртуальной камеры pyvirtualcam и предварительно загружает все изображения.
    Размеры камеры теперь определяются размерами фонового изображения BG.png/gif.
    Эта функция предназначена для вызова из gui_elements.py.
    """
    global virtual_cam_obj, CAM_WIDTH, CAM_HEIGHT, CAM_FPS
    global _background_frames_list, _original_background_fps, _avatar_frames_map, _current_active_avatar_frames, _avatar_frames_lock
    global _bouncing_enabled, _current_background_frame_float_index
    global _cross_fade_enabled, CROSS_FADE_DURATION_MS, _reset_animation_on_status_change, _instant_talk_transition
    global _dim_enabled, DIM_PERCENTAGE

    # Close existing camera if it's active before re-initializing
    if virtual_cam_obj is not None and virtual_cam_obj is not False:
        print("Виртуальная камера уже активна. Закрываю перед повторной инициализацией.")
        try:
            virtual_cam_obj.close()
        except Exception as e:
            print(f"Ошибка при закрытии существующей виртуальной камеры: {e}")
        virtual_cam_obj = None  # Ensure it's explicitly None

    print("\n--- Инициализация виртуальной камеры и предварительная загрузка изображений/анимаций ---")

    config = config_manager.load_config()  # Always load the latest config

    # Update all global variables from config
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
        CAM_FPS = CAM_FPS_from_config if CAM_FPS_from_config > 0 else _initial_cam_fps_default
    except ValueError:
        CAM_FPS = _initial_cam_fps_default

    # Загружаем фон и аватары первыми.
    # CAM_WIDTH и CAM_HEIGHT будут установлены функцией _load_frames_from_file при загрузке BG.
    _background_frames_list, _original_background_fps = _load_frames_from_file(BACKGROUND_IMAGE_PATH, is_avatar=False, resize_to_cam=True)
    if not _background_frames_list:
        print("КРИТИЧЕСКАЯ ОШИБКА: Не удалось загрузить фоновое изображение. Не могу инициализировать камеру.")
        virtual_cam_obj = False  # Signal failure to launch camera
        return

    # Load avatars
    for status, filename in STATUS_TO_FILENAME_MAP.items():
        frames, original_fps = _load_frames_from_file(filename, is_avatar=True)
        _avatar_frames_map[status] = {"frames": frames, "original_fps": original_fps, "current_float_index": 0.0}
        if not frames:
            print(f"ПРЕДУПРЕЖДЕНИЕ: Не удалось загрузить аватар для статуса '{status}'. Использую пустой набор кадров.")

    # Проверка, что CAM_WIDTH и CAM_HEIGHT были установлены
    if CAM_WIDTH == 0 or CAM_HEIGHT == 0:
        print("КРИТИЧЕСКАЯ ОШИБКА: Размеры камеры не были определены из фонового изображения. Использую стандартное разрешение 640x360.")
        CAM_WIDTH = 640
        CAM_HEIGHT = 360

    try:
        fade_duration_from_config = int(config.get('CROSS_FADE_DURATION_MS', str(_initial_cross_fade_duration_default)))
        CROSS_FADE_DURATION_MS = fade_duration_from_config if fade_duration_from_config >= 0 else _initial_cross_fade_duration_default
    except ValueError:
        CROSS_FADE_DURATION_MS = _initial_cross_fade_duration_default

    # Set initial active avatar (e.g., "Inactive")
    with _avatar_frames_lock:
        _current_active_avatar_frames = _avatar_frames_map.get("Молчит", {"frames": [], "original_fps": 1.0,
                                                                          "current_float_index": 0.0})
        _current_background_frame_float_index = 0.0

    try:
        print(f"Создание виртуальной камеры: {CAM_WIDTH}x{CAM_HEIGHT} @ {CAM_FPS} FPS...")
        virtual_cam_obj = pyvirtualcam.Camera(width=CAM_WIDTH, height=CAM_HEIGHT, fps=CAM_FPS, print_fps=False,
                                              fmt=pyvirtualcam.PixelFormat.RGB)
        print("Виртуальная камера успешно создана.")

        initial_avatar_data = _avatar_frames_map.get("Молчит",
                                                     {"frames": [], "original_fps": 1.0, "current_float_index": 0.0})
        initial_avatar_frames = initial_avatar_data['frames']

        if not initial_avatar_frames:
            initial_avatar_frames = [np.zeros((CAM_HEIGHT, CAM_WIDTH, 4), dtype=np.uint8)]
            print("ПРЕДУПРЕЖДЕНИЕ: Нет кадров для 'Молчит' при инициализации. Использую заглушку.")

        initial_frame = _compose_frame(_background_frames_list[0], initial_avatar_frames[0], y_offset_addition=0)
        virtual_cam_obj.send(initial_frame)
        virtual_cam_obj.sleep_until_next_frame()

        try:
            while not display_queue.empty():  # Clear queue before putting initial frame
                display_queue.get_nowait()
            display_queue.put_nowait(initial_frame)
        except queue.Full:
            pass

    except Exception as e:
        print(f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось инициализировать виртуальную камеру: {e}")
        print(
            "Пожалуйста, убедитесь, что у вас установлен драйвер виртуальной камеры (например, OBS Virtual Camera) и вы запустили 'pip install pyvirtualcam opencv-python Pillow'.")
        virtual_cam_obj = False  # Mark as failed initialization


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

    print("\n--- Обновление параметров виртуальной камеры в рантайме (только глобальные переменные) ---")

    # old_cam_width и old_cam_height не нужны для сравнения, так как они не могут измениться без перезапуска
    # virtual_camera.initialize_virtual_camera(), которая их устанавливает из BG.
    old_cam_fps = CAM_FPS

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
        CAM_FPS = CAM_FPS_from_config if CAM_FPS_from_config > 0 else _initial_cam_fps_default
    except ValueError:
        CAM_FPS = _initial_cam_fps_default

    # CAM_WIDTH и CAM_HEIGHT не обновляются здесь из конфига, они устанавливаются initialize_virtual_camera
    # на основе фонового изображения.
    print(f"  Разрешение камеры остается: {CAM_WIDTH}x{CAM_HEIGHT}")


    try:
        fade_duration_from_config = int(config.get('CROSS_FADE_DURATION_MS', str(_initial_cross_fade_duration_default)))
        CROSS_FADE_DURATION_MS = fade_duration_from_config if fade_duration_from_config >= 0 else _initial_cross_fade_duration_default
    except ValueError:
        CROSS_FADE_DURATION_MS = _initial_cross_fade_duration_default

    # Set flag if critical camera parameters changed (only FPS matters now)
    if old_cam_fps != CAM_FPS:
        _camera_needs_restart = True
        print("Параметры камеры (FPS) изменились. Сигнализирую GUI о необходимости перезапуска камеры.")
    else:
        _camera_needs_restart = False
        print("Параметры камеры (FPS) не изменились. Обновлены только внутренние настройки анимации.")

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
    import time
    t0 = time.perf_counter()
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
    if CHECK_TIME:
        t1 = time.perf_counter()
        print(f"[ПРОФИЛЬ] Масштаб BG: {(t1 - t0)*1000:.2f} мс")

    # Остальная логика наложения аватара остается прежней
    if avatar_rgba_image is None or avatar_rgba_image.shape[0] == 0 or avatar_rgba_image.shape[1] == 0:

        if CHECK_TIME:
            t4 = time.perf_counter()
            print(f"[ПРОФИЛЬ] Всего: {(t4 - t0)*1000:.2f} мс")
        return output_frame

    avatar_height, avatar_width, _ = avatar_rgba_image.shape
    # Максимальный размер аватара относительно ВЫСОТЫ/ШИРИНЫ камеры
    max_avatar_dim = min(CAM_WIDTH, CAM_HEIGHT) * 0.7

    new_avatar_w = int(avatar_width)
    new_avatar_h = int(avatar_height)
    # Проверка: аватар масштабирован?
    avatar_was_scaled = (new_avatar_w != avatar_width or new_avatar_h != avatar_height)

    if new_avatar_w <= 0 or new_avatar_h <= 0:
        if CHECK_TIME:
            t4 = time.perf_counter()
            print(f"[ПРОФИЛЬ] Всего: {(t4 - t0)*1000:.2f} мс")
        return output_frame

    # Используем cv2.INTER_LINEAR для масштабирования аватара
    avatar_resized = cv2.resize(avatar_rgba_image, (new_avatar_w, new_avatar_h), interpolation=cv2.INTER_LINEAR)

    # Центрируем аватар относительно CAM_WIDTH/CAM_HEIGHT
    # Позиционируем аватар строго в левый нижний угол
    x_offset = (CAM_WIDTH - new_avatar_w) // 2
    # Смещаем аватар ниже, если масштабирован и включено подпрыгивание
    total_bounce_range = BOUNCING_MAX_OFFSET_PIXELS if avatar_was_scaled and _bouncing_enabled else 0
    y_offset = CAM_HEIGHT - new_avatar_h + total_bounce_range + y_offset_addition

    if CHECK_TIME:
        t2 = time.perf_counter()
        print(f"[ПРОФИЛЬ] Подготовка аватара: {(t2 - t1)*1000:.2f} мс")
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
        if CHECK_TIME:
            t4 = time.perf_counter()
            print(f"[ПРОФИЛЬ] Всего: {(t4 - t0)*1000:.2f} мс")
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
        if CHECK_TIME:
            t4 = time.perf_counter()
            print(f"[ПРОФИЛЬ] Всего: {(t4 - t0)*1000:.2f} мс")
        return output_frame

    bg_roi = output_frame[y1_clip:y2_clip, x1_clip:x2_clip].astype(np.float32)

    blended_roi = avatar_rgb_clipped * alpha_factor_clipped + \
                  bg_roi * (1 - alpha_factor_clipped)

    if CHECK_TIME:
        t3 = time.perf_counter()
        print(f"[ПРОФИЛЬ] Blending: {(t3 - t2)*1000:.2f} мс")
    output_frame[y1_clip:y2_clip, x1_clip:x2_clip] = blended_roi.astype(np.uint8)

    if CHECK_TIME:
        t4 = time.perf_counter()
        print(f"[ПРОФИЛЬ] Всего: {(t4 - t0)*1000:.2f} мс")
    return output_frame


def get_static_preview_frame(current_status: str) -> np.ndarray:
    """
    Возвращает статичный кадр для предварительного просмотра в GUI,
    используя первый кадр фона и первый кадр текущего активного аватара.
    Принимает текущий статус для отображения соответствующего аватара.
    """
    global _background_frames_list, CAM_WIDTH, CAM_HEIGHT, _avatar_frames_map

    # Используем CAM_WIDTH и CAM_HEIGHT, так как _compose_frame уже обработает масштабирование
    if not _background_frames_list or CAM_WIDTH == 0 or CAM_HEIGHT == 0:
        print(
            "ПРЕДУПРЕЖДЕНИЕ (get_static_preview_frame): Фон не загружен или размеры камеры не определены. Возвращаю пустой кадр.")
        return np.zeros((360, 640, 3), dtype=np.uint8)

    avatar_data_for_preview = _avatar_frames_map.get(current_status,
                                                     {"frames": [], "original_fps": 1.0, "current_float_index": 0.0})
    avatar_frames_for_preview = avatar_data_for_preview['frames']

    if not avatar_frames_for_preview:
        fallback_data = _avatar_frames_map.get("Молчит",
                                               {"frames": [], "original_fps": 1.0, "current_float_index": 0.0})
        fallback_frames = fallback_data['frames']
        print(
            f"ПРЕДУПРЕЖДЕНИЕ (get_static_preview_frame): Кадры для статуса '{current_status}' не найдены. Использую 'Молчит' ({len(fallback_frames)} кадров) для предпросмотра.")
        avatar_frames_for_preview = fallback_frames  # Use fallback if original is empty

    preview_frame = _compose_frame(_background_frames_list[0], avatar_frames_for_preview[0], y_offset_addition=0)
    return preview_frame


async def start_frame_sending_loop():
    """
    Асинхронный цикл, который постоянно генерирует и отправляет кадры в виртуальную камеру.
    Эта функция предполагает, что виртуальная камера уже инициализирована.
    """
    global _current_background_frame_index, _current_background_frame_float_index
    global _cam_loop_running, display_queue, virtual_cam_obj, _current_active_avatar_frames, _avatar_frames_map, _avatar_frames_lock
    global _bouncing_enabled, BOUNCING_MAX_OFFSET_PIXELS, _bouncing_active, _bouncing_start_time, _original_background_fps, CAM_FPS
    global _cross_fade_active, _cross_fade_start_time, _old_avatar_frames_data, _cross_fade_enabled, CROSS_FADE_DURATION_MS
    global _dim_enabled, DIM_PERCENTAGE  # Добавлены новые глобальные переменные

    _cam_loop_running = True

    while _cam_loop_running:
        current_bounce_offset = 0

        # --- Логика расчета смещения для разового подпрыгивания ---
        if _bouncing_active and _bouncing_enabled:
            elapsed_ms = (time.time() - _bouncing_start_time) * 1000
            if elapsed_ms >= BOUNCING_DURATION_MS:
                _bouncing_active = False
                current_bounce_offset = 0
            else:
                progress = elapsed_ms / BOUNCING_DURATION_MS
                current_bounce_offset = int(-BOUNCING_MAX_OFFSET_PIXELS * math.sin(progress * math.pi))

        try:
            # Если камера не была успешно инициализирована или была отключена, пауза и продолжение
            if virtual_cam_obj is False or virtual_cam_obj is None:
                # print("ПРЕДУПРЕЖДЕНИЕ: Виртуальная камера не активна. Кадры не отправляются.")
                await asyncio.sleep(POLLING_INTERVAL_SECONDS)  # Пауза, чтобы не нагружать ЦПУ
                continue  # Продолжаем цикл, ожидая, что камера может быть инициализирована позже

            final_avatar_image_rgba = None

            with _avatar_frames_lock:
                # --- Обработка фонового кадра ---
                background_idx_to_use = 0
                if _background_frames_list:
                    # Рассчитываем коэффициент продвижения кадров для фона
                    # Убедимся, что _original_background_fps не равен нулю, чтобы избежать деления на ноль
                    effective_original_background_fps = _original_background_fps if _original_background_fps > 0 else 1.0
                    frame_advance_factor_bg = effective_original_background_fps / CAM_FPS

                    _current_background_frame_float_index = (
                                                                    _current_background_frame_float_index + frame_advance_factor_bg) % len(
                        _background_frames_list)
                    background_idx_to_use = int(math.floor(_current_background_frame_float_index))
                    background_frame_to_composite = _background_frames_list[
                        background_idx_to_use] if _background_frames_list else np.zeros((CAM_HEIGHT, CAM_WIDTH, 3),
                                                                                        dtype=np.uint8)
                else:
                    print("ПРЕДУПРЕЖДЕНИЕ: Список фоновых кадров пуст. Используется индекс 0.")
                    background_frame_to_composite = np.zeros((CAM_HEIGHT, CAM_WIDTH, 3), dtype=np.uint8)

                # --- Обработка аватара (с кроссфейдом или без) ---
                current_avatar_data = _current_active_avatar_frames
                current_avatar_frames_list = current_avatar_data.get('frames', [])
                current_original_avatar_fps = current_avatar_data.get('original_fps', 1.0)
                # Получаем текущий плавающий индекс из данных аватара
                current_avatar_float_index_for_use = current_avatar_data.get('current_float_index', 0.0)


                if current_avatar_frames_list:
                    # Убедимся, что current_original_avatar_fps не равен нулю
                    effective_original_avatar_fps = current_original_avatar_fps if current_original_avatar_fps > 0 else 1.0
                    frame_advance_factor_current = effective_original_avatar_fps / CAM_FPS
                    # Обновляем плавающий индекс и сохраняем его обратно в данных аватара
                    current_avatar_data['current_float_index'] = (
                                                                         current_avatar_float_index_for_use + frame_advance_factor_current) % len(
                        current_avatar_frames_list)
                    avatar_idx_to_use_current = int(math.floor(current_avatar_data['current_float_index']))
                    current_avatar_rgba = current_avatar_frames_list[avatar_idx_to_use_current].copy()
                else:
                    current_avatar_rgba = np.zeros((CAM_HEIGHT, CAM_WIDTH, 4), dtype=np.uint8)


                if _cross_fade_active and _cross_fade_enabled:
                    elapsed_ms_fade = (time.time() - _cross_fade_start_time) * 1000
                    if elapsed_ms_fade >= CROSS_FADE_DURATION_MS:
                        _cross_fade_active = False
                        final_avatar_image_rgba = current_avatar_rgba
                        _old_avatar_frames_data = {"frames": [], "original_fps": 1.0, "current_float_index": 0.0}
                    else:
                        fade_progress = elapsed_ms_fade / CROSS_FADE_DURATION_MS
                        old_opacity = 1.0 - fade_progress
                        new_opacity = fade_progress

                        old_avatar_frames_list = _old_avatar_frames_data.get('frames', [])
                        old_original_avatar_fps = _old_avatar_frames_data.get('original_fps', 1.0)
                        # Получаем плавающий индекс старого аватара из его данных
                        old_avatar_float_index_for_use = _old_avatar_frames_data.get('current_float_index', 0.0)

                        old_avatar_rgba = np.zeros((CAM_HEIGHT, CAM_WIDTH, 4), dtype=np.uint8)
                        if old_avatar_frames_list:
                            effective_old_original_avatar_fps = old_original_avatar_fps if old_original_avatar_fps > 0 else 1.0
                            frame_advance_factor_old = effective_old_original_avatar_fps / CAM_FPS
                            # Обновляем плавающий индекс старого аватара и сохраняем его обратно
                            _old_avatar_frames_data['current_float_index'] = (
                                                                                     old_avatar_float_index_for_use + frame_advance_factor_old) % len(
                                old_avatar_frames_list)
                            avatar_idx_to_use_old = int(math.floor(_old_avatar_frames_data['current_float_index']))
                            old_avatar_rgba = old_avatar_frames_list[avatar_idx_to_use_old].copy()

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


            composed_frame_rgb = _compose_frame(background_frame_to_composite, final_avatar_image_rgba,
                                                y_offset_addition=current_bounce_offset)

            if composed_frame_rgb is not None:
                try:
                    virtual_cam_obj.send(composed_frame_rgb)
                    virtual_cam_obj.sleep_until_next_frame()

                    try:
                        while not display_queue.empty():
                            display_queue.get_nowait()
                        display_queue.put_nowait(composed_frame_rgb)
                    except queue.Full:
                        pass
                except Exception as e:
                    print(f"ОШИБКА отправки кадра в виртуальную камеру или GUI: {e}")
                    virtual_cam_obj = False
            else:
                virtual_cam_obj.send(background_frame_to_composite)
                virtual_cam_obj.sleep_until_next_frame()
                try:
                    while not display_queue.empty():
                        display_queue.get_nowait()
                    display_queue.put_nowait(background_frame_to_composite)
                except queue.Full:
                    pass

        except Exception as e:
            print(f"ОШИБКА в цикле генерации кадров: {e}")
            await asyncio.sleep(POLLING_INTERVAL_SECONDS) # Используем POLLING_INTERVAL_SECONDS


def voice_status_callback(status_message: str, debug_message: str):
    """
    Эта функция вызывается при каждом изменении статуса голоса.
    Она обновляет набор кадров аватара для отображения и выводит статус в консоль.
    """
    global _current_active_avatar_frames, _current_avatar_frame_index
    global _status_change_listener, _avatar_frames_lock, _avatar_frames_map
    global _bouncing_active, _bouncing_start_time, _bouncing_enabled, _last_known_voice_status
    global _cross_fade_active, _cross_fade_start_time, _old_avatar_frames_data, _cross_fade_enabled, CROSS_FADE_DURATION_MS
    global _reset_animation_on_status_change, _instant_talk_transition

    if _status_change_listener:
        _status_change_listener(status_message, debug_message)

    with _avatar_frames_lock:
        # Убедимся, что дефолтная заглушка также имеет full data structure
        new_active_avatar_data = _avatar_frames_map.get(status_message,
                                                        {"frames": [], "original_fps": 1.0, "current_float_index": 0.0})

        # Сравниваем объекты, чтобы определить, действительно ли это новый набор кадров
        if new_active_avatar_data is not _current_active_avatar_frames:
            # Логика для INSTANT_TALK_TRANSITION: если включен и статус "Говорит"
            if _instant_talk_transition and status_message == "Говорит":
                _cross_fade_active = False  # Отключаем кроссфейд для этого перехода
                _old_avatar_frames_data = {"frames": [], "original_fps": 1.0,
                                           "current_float_index": 0.0}  # Очищаем старые данные для чистого появления
            elif _cross_fade_enabled:  # Если INSTANT_TALK_TRANSITION не активен или не статус "Говорит", и кроссфейд включен
                _old_avatar_frames_data = _current_active_avatar_frames
                _cross_fade_active = True
                _cross_fade_start_time = time.time()
            else:  # Если кроссфейд выключен
                _cross_fade_active = False
                _old_avatar_frames_data = {"frames": [], "original_fps": 1.0, "current_float_index": 0.0}

            # Обновляем текущий активный аватар
            _current_active_avatar_frames = new_active_avatar_data
            _current_avatar_frame_index = 0  # Целочисленный индекс сбрасываем

            # Применяем логику сброса/продолжения анимации для НОВОГО активного аватара
            # Если это мгновенный переход на "Говорит" или сброс включен, сбрасываем индекс
            if (
                    _instant_talk_transition and status_message == "Говорит") or _reset_animation_on_status_change:
                _current_active_avatar_frames['current_float_index'] = 0.0
                # else: если RESET_ANIMATION_ON_STATUS_CHANGE False,
            # new_active_avatar_data['current_float_index'] сохраняет свое предыдущее значение для этого статуса.

            # Если для нового статуса нет кадров, используем запасной вариант 'Молчит'
            if not new_active_avatar_data['frames']:
                fallback_data = _avatar_frames_map.get("Молчит",
                                                       {"frames": [], "original_fps": 1.0, "current_float_index": 0.0})
                fallback_frames = fallback_data['frames']
                if fallback_data is not _current_active_avatar_frames:
                    _current_active_avatar_frames = fallback_data
                    _current_avatar_frame_index = 0
                    if (
                            _instant_talk_transition and status_message == "Говорит") or _reset_animation_on_status_change:  # Сброс и для запасного варианта
                        _current_active_avatar_frames['current_float_index'] = 0.0
                    print(
                        f"ПРЕДУПРЕЖДЕНИЕ (voice_status_callback): Кадры для статуса '{status_message}' не найдены. Использую запасной вариант 'Молчит' ({len(fallback_frames)} кадров).")
                else:
                    pass

                if not fallback_frames:
                    print(
                        "КРИТИЧЕСКОЕ ПРЕДУПРЕЖДЕНИЕ: Нет доступных кадров ни для текущего статуса, ни для 'Молчит'. Анимация аватара будет пустой.")

        # --- Логика запуска анимации подпрыгивания ---
        if (status_message == "Говорит" and
                _bouncing_enabled and
                not _bouncing_active):

            if _last_known_voice_status != "Говорит":
                _bouncing_active = True
                _bouncing_start_time = time.time()

        _last_known_voice_status = status_message


def shutdown_virtual_camera():
    """Закрывает объект виртуальной камеры и останавливает цикл отправки кадров."""
    global virtual_cam_obj, _cam_loop_running

    _cam_loop_running = False  # This will cause the asyncio loop in the thread to terminate

    if virtual_cam_obj and virtual_cam_obj is not False:
        print("Закрытие виртуальной камеры...")
        try:
            virtual_cam_obj.close()
            virtual_cam_obj = None
            print("Виртуальная камера закрыта.")
        except Exception as e:
            print(f"Ошибка при закрытии виртуальной камеры: {e}")
            virtual_cam_obj = None  # Ensure it's None even if close fails


# Этот блок будет выполнен только при прямом запуске virtual_camera.py,
# а не при импорте.
if __name__ == '__main__':
    print("Запуск virtual_camera.py напрямую для тестирования...")
    pass
