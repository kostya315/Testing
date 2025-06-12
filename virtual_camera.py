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

# --- КОНФИГУРАЦИЯ ПУТЕЙ ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Папка для всех обработанных аватаров и статических изображений (фона, оверлеев)
# Это папка, с которой работает пользователь.
AVATAR_ASSETS_FOLDER = os.path.join(SCRIPT_DIR, "reactive_avatar")

# Глобальные переменные для размеров и FPS камеры (размеры будут определены динамически)
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
# _avatar_frames_map теперь будет хранить словари: "статус" -> {"frames": [...], "original_fps": X}
_avatar_frames_map = {}

# Индексы текущих кадров для анимации
_current_avatar_frame_index = 0  # Целочисленный индекс (для совместимости, основной - float)
_current_avatar_frame_float_index = 0.0  # Плавающий индекс для точного воспроизведения GIF
_current_background_frame_index = 0  # Целочисленный индекс (для совместимости, основной - float)
_current_background_frame_float_index = 0.0  # Плавающий индекс для точного воспроизведения GIF фона

# Текущий активный набор кадров аватара (устанавливается voice_status_callback)
# Теперь это будет словарь: {"frames": [...], "original_fps": X}
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

# Добавляем переменную для отслеживания последнего известного статуса голоса
_last_known_voice_status = None

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

# Базовое имя для фонового изображения (изменено по запросу пользователя)
BACKGROUND_IMAGE_PATH = "BG"


def set_status_callback(callback_func):
    """Устанавливает функцию обратного вызова для обновления статуса."""
    global _status_change_listener
    _status_change_listener = callback_func


def _load_frames_from_file(base_name: str, is_avatar: bool = False):
    """
    Загружает кадры из GIF или PNG файла.
    Пытается загрузить GIF, если не найдет, то PNG.
    Возвращает список NumPy массивов (RGBA для аватаров, RGB для фона) и оригинальный FPS.
    """
    gif_path = os.path.join(AVATAR_ASSETS_FOLDER, f"{base_name}.gif")
    png_path = os.path.join(AVATAR_ASSETS_FOLDER, f"{base_name}.png")
    frames = []
    # Важно: original_fps по умолчанию должен быть не CAM_FPS, а некоторое базовое значение
    # или же передаваться как аргумент, так как CAM_FPS еще может быть не инициализирован.
    # Но для целей загрузки, когда CAM_FPS уже установлен из конфига, это будет актуальное значение.
    original_fps = 30.0  # Временное дефолтное значение для загрузки, если CAM_FPS еще не определен

    # Если CAM_FPS уже установлен (после initialize_virtual_camera), используем его.
    # Иначе - используем дефолтное значение 30.0, чтобы избежать ошибок.
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
        if file_to_load.endswith(".gif"):
            with Image.open(file_to_load) as im:
                # Извлекаем все кадры из GIF
                for frame in ImageSequence.Iterator(im):
                    frames.append(np.array(frame.convert("RGBA" if is_avatar else "RGB")))

                # Попытка определить FPS GIF
                # Если в GIF есть информация о продолжительности, используем её
                # im.info.get('duration') обычно дает задержку в мс для КАЖДОГО кадра
                if 'duration' in im.info and im.info['duration'] > 0:
                    original_fps = 1000.0 / im.info['duration']
                elif frames:
                    print(
                        f"  ПРЕДУПРЕЖДЕНИЕ: Не удалось определить точный FPS для GIF '{base_name}'. Использую дефолтный FPS ({original_fps:.2f}).")
                else:
                    original_fps = 1.0  # Если кадров нет, то и FPS не нужен, но возвращаем 1.0

        else:  # PNG (статичное изображение)
            with Image.open(file_to_load) as im:
                frames.append(np.array(im.convert("RGBA" if is_avatar else "RGB")))
                original_fps = 1.0  # Статичное изображение, по сути 1 кадр в секунду

    except Exception as e:
        print(f"  ОШИБКА: Не удалось загрузить кадры из '{file_to_load}': {e}")
        return [], original_fps  # Возвращаем дефолтный FPS в случае ошибки

    return frames, original_fps


def initialize_virtual_camera():
    """
    Инициализирует объект виртуальной камеры pyvirtualcam и предварительно загружает все изображения.
    Эта функция вызывается только один раз из main_script.py.
    """
    global virtual_cam_obj, CAM_WIDTH, CAM_HEIGHT, CAM_FPS
    global _background_frames_list, _original_background_fps, _avatar_frames_map, _current_active_avatar_frames, _avatar_frames_lock
    global _bouncing_enabled, _current_avatar_frame_float_index, _current_background_frame_float_index

    if virtual_cam_obj is not None and virtual_cam_obj is not False:
        print("Виртуальная камера уже инициализирована.")
        return

    print("\n--- Предварительная загрузка изображений и анимаций ---")

    # --- Загрузка конфигурации для BOUNCING_ENABLED и CAM_FPS ---
    config = config_manager.load_config()
    _bouncing_enabled = config.get('BOUNCING_ENABLED', 'True').lower() == 'true'
    # print(f"Флаг BOUNCING_ENABLED из конфига: {_bouncing_enabled}") # УДАЛЕНО

    # Считываем CAM_FPS из конфига, если есть, иначе используем значение по умолчанию
    try:
        CAM_FPS_from_config = int(config.get('CAM_FPS', str(_initial_cam_fps_default)))
        if CAM_FPS_from_config <= 0:  # Убедимся, что FPS положительный
            print(
                f"ПРЕДУПРЕЖДЕНИЕ: Недопустимое значение CAM_FPS в конфиге: {CAM_FPS_from_config}. Использован стандартный FPS: {_initial_cam_fps_default}.")
            CAM_FPS = _initial_cam_fps_default
        else:
            CAM_FPS = CAM_FPS_from_config
    except ValueError:
        print(
            f"ПРЕДУПРЕЖДЕНИЕ: Некорректный формат CAM_FPS в конфиге. Использован стандартный FPS: {_initial_cam_fps_default}.")
        CAM_FPS = _initial_cam_fps_default

    # print(f"Используемый FPS камеры: {CAM_FPS}.") # УДАЛЕНО

    # Загрузка фонового изображения (всегда обрабатывается как не-аватар)
    _background_frames_list, _original_background_fps = _load_frames_from_file(BACKGROUND_IMAGE_PATH, is_avatar=False)
    if not _background_frames_list:
        print("КРИТИЧЕСКАЯ ОШИБКА: Не удалось загрузить фоновое изображение. Не могу инициализировать камеру.")
        virtual_cam_obj = False
        return

    # Определяем размеры камеры по первому кадру фона
    # print(f"Разрешение камеры установлено по фону: {CAM_WIDTH}x{CAM_HEIGHT} @ {CAM_FPS} FPS.") # УДАЛЕНО
    CAM_HEIGHT, CAM_WIDTH, _ = _background_frames_list[0].shape

    # Загрузка аватаров и их оригинальных FPS
    for status, filename in STATUS_TO_FILENAME_MAP.items():
        frames, original_fps = _load_frames_from_file(filename, is_avatar=True)
        _avatar_frames_map[status] = {"frames": frames, "original_fps": original_fps}
        if not frames:
            print(f"ПРЕДУПРЕЖДЕНИЕ: Не удалось загрузить аватар для статуса '{status}'. Использую пустой набор кадров.")

    # Диагностический вывод после загрузки всех аватаров
    # print("DEBUG (initialize_virtual_camera): Содержимое _avatar_frames_map после загрузки:") # УДАЛЕНО
    # for status, data in _avatar_frames_map.items(): # УДАЛЕНО
    #     print(f"  Статус '{status}' (файл '{STATUS_TO_FILENAME_MAP.get(status, 'N/A')}'): {len(data['frames'])} кадров, {data['original_fps']:.2f} FPS") # УДАЛЕНО

    # Устанавливаем начальный активный аватар (например, "Молчит")
    with _avatar_frames_lock:
        _current_active_avatar_frames = _avatar_frames_map.get("Молчит", {"frames": [], "original_fps": CAM_FPS})
        _current_avatar_frame_index = 0
        _current_avatar_frame_float_index = 0.0
        _current_background_frame_float_index = 0.0
        # print(f"DEBUG (initialize_virtual_camera): Начальный активный аватар 'Молчит' имеет {len(_current_active_avatar_frames.get('frames', []))} кадров (после блокировки).") # УДАЛЕНО

    try:
        print(f"Инициализация виртуальной камеры: {CAM_WIDTH}x{CAM_HEIGHT} @ {CAM_FPS} FPS...")
        # Устанавливаем формат пикселей RGB, так как _compose_frame возвращает RGB
        virtual_cam_obj = pyvirtualcam.Camera(width=CAM_WIDTH, height=CAM_HEIGHT, fps=CAM_FPS, print_fps=False,
                                              fmt=pyvirtualcam.PixelFormat.RGB)
        print("Виртуальная камера успешно инициализирована.")

        # Получаем первый кадр для инициализации
        initial_avatar_data = _avatar_frames_map.get("Молчит", {"frames": [], "original_fps": CAM_FPS})
        initial_avatar_frames = initial_avatar_data['frames']

        if not initial_avatar_frames:
            initial_avatar_frames = [
                np.zeros((CAM_HEIGHT, CAM_WIDTH, 4),
                         dtype=np.uint8)]  # Если даже "Молчит" пуст, используем пустой черный квадрат
            print("ПРЕДУПРЕЖДЕНИЕ: Нет кадров для 'Молчит' при инициализации. Использую заглушку.")

        # Композируем первый кадр для инициализации GUI (без смещения)
        # Отправляем первый кадр напрямую
        initial_frame = _compose_frame(0, 0, initial_avatar_frames, y_offset_addition=0)
        virtual_cam_obj.send(initial_frame)
        virtual_cam_obj.sleep_until_next_frame()

        try:  # Также для GUI
            display_queue.put_nowait(initial_frame)
        except queue.Full:
            pass

    except Exception as e:
        print(f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось инициализировать виртуальную камеру: {e}")
        print(
            "Пожалуйста, убедитесь, что у вас установлен драйвер виртуальной камеры (например, OBS Virtual Camera) и вы запустили 'pip install pyvirtualcam opencv-python Pillow'.")
        virtual_cam_obj = False


def _compose_frame(bg_frame_idx: int, avatar_frame_idx: int, avatar_frames: list[np.ndarray],
                   y_offset_addition: int = 0) -> np.ndarray:
    """
    Композирует текущий кадр фона и заданный кадр аватара, применяя опциональное смещение по Y.
    Возвращает NumPy массив RGB для отправки в виртуальную камеру.
    """
    global _background_frames_list, CAM_WIDTH, CAM_HEIGHT

    if CAM_WIDTH == 0 or CAM_HEIGHT == 0 or not _background_frames_list:
        return np.zeros((480, 640, 3), dtype=np.uint8)

    background_frame_rgb = _background_frames_list[bg_frame_idx % len(_background_frames_list)].copy()

    if not avatar_frames:
        return background_frame_rgb

    effective_avatar_frame_idx = avatar_frame_idx % len(avatar_frames)
    avatar_frame_rgba = avatar_frames[effective_avatar_frame_idx].copy()

    # Изменяем размер аватара для наложения (например, 70% от высоты/ширины камеры, сохраняя пропорции)
    avatar_height, avatar_width, _ = avatar_frame_rgba.shape

    max_avatar_dim = min(CAM_WIDTH, CAM_HEIGHT) * 0.7

    if avatar_width > 0 and avatar_height > 0:
        scale_factor_w = max_avatar_dim / avatar_width
        scale_factor_h = max_avatar_dim / avatar_height
        scale_factor = min(scale_factor_w, scale_factor_h)
    else:
        scale_factor = 0

    new_avatar_w = int(avatar_width * scale_factor)
    new_avatar_h = int(avatar_height * scale_factor)

    if new_avatar_w <= 0 or new_avatar_h <= 0:
        return background_frame_rgb

    avatar_resized = cv2.resize(avatar_frame_rgba, (new_avatar_w, new_avatar_h), interpolation=cv2.INTER_AREA)

    # Применяем дополнительное смещение по Y к центру
    x_offset = (CAM_WIDTH - new_avatar_w) // 2
    # Явно преобразуем y_offset в int
    y_offset = int((CAM_HEIGHT - new_avatar_h) // 2 + y_offset_addition)

    avatar_rgb_float = avatar_resized[:, :, :3].astype(np.float32)
    alpha_channel_float = avatar_resized[:, :, 3].astype(np.float32) / 255.0
    alpha_factor_3_chan = cv2.merge([alpha_channel_float, alpha_channel_float, alpha_channel_float])

    y1, y2 = y_offset, y_offset + new_avatar_h
    x1, x2 = x_offset, x_offset + new_avatar_w

    # Убедимся, что координаты не выходят за границы кадра
    y2 = min(y2, CAM_HEIGHT)
    x2 = min(x2, CAM_WIDTH)
    y1 = max(0, y1)
    x1 = max(0, x1)

    actual_h = y2 - y1
    actual_w = x2 - x1

    # Также убедимся, что обрезанный аватар соответствует области ROI
    avatar_rgb_clipped = avatar_rgb_float[0:actual_h, 0:actual_w]
    alpha_factor_clipped = alpha_factor_3_chan[0:actual_h, 0:actual_w]

    if actual_h <= 0 or actual_w <= 0 or avatar_rgb_clipped.shape[0] == 0 or avatar_rgb_clipped.shape[1] == 0:
        return background_frame_rgb

    bg_roi = background_frame_rgb[y1:y2, x1:x2].astype(np.float32)

    blended_roi = avatar_rgb_clipped * alpha_factor_clipped + \
                  bg_roi * (1 - alpha_factor_clipped)

    background_frame_rgb[y1:y2, x1:x2] = blended_roi.astype(np.uint8)

    return background_frame_rgb


def get_static_preview_frame(current_status: str) -> np.ndarray:
    """
    Возвращает статичный кадр для предварительного просмотра в GUI,
    используя первый кадр фона и первый кадр текущего активного аватара.
    Принимает текущий статус для отображения соответствующего аватара.
    """
    global _background_frames_list, CAM_WIDTH, CAM_HEIGHT, _avatar_frames_map

    if not _background_frames_list or CAM_WIDTH == 0 or CAM_HEIGHT == 0:
        print(
            "ПРЕДУПРЕЖДЕНИЕ (get_static_preview_frame): Фон не загружен или размеры камеры не определены. Возвращаю пустой кадр.")
        return np.zeros((480, 640, 3), dtype=np.uint8)

    # Используем первый кадр из _avatar_frames_map для заданного статуса.
    # Если кадры для статуса пусты, используем кадры 'Молчит' как запасной вариант.
    avatar_data_for_preview = _avatar_frames_map.get(current_status, {"frames": [], "original_fps": CAM_FPS})
    avatar_frames_for_preview = avatar_data_for_preview['frames']

    if not avatar_frames_for_preview:
        fallback_data = _avatar_frames_map.get("Молчит", {"frames": [], "original_fps": CAM_FPS})
        avatar_frames_for_preview = fallback_data['frames']
        print(
            f"ПРЕДУПРЕЖДЕНИЕ (get_static_preview_frame): Кадры для статуса '{current_status}' не найдены. Использую 'Молчит' ({len(avatar_frames_for_preview)} кадров) для предпросмотра.")

    # Композируем первый кадр для предпросмотра (без смещения)
    preview_frame = _compose_frame(0, 0, avatar_frames_for_preview, y_offset_addition=0)
    # print(f"DEBUG (get_static_preview_frame): Возвращаю статичный кадр предпросмотра для статуса '{current_status}'.") # УДАЛЕНО
    return preview_frame


async def start_frame_sending_loop():
    """
    Асинхронный цикл, который постоянно генерирует и отправляет кадры в виртуальную камеру.
    Эта функция предполагает, что виртуальная камера уже инициализирована.
    """
    global _current_avatar_frame_index, _current_avatar_frame_float_index, _current_background_frame_index, _current_background_frame_float_index
    global _cam_loop_running, display_queue, virtual_cam_obj, _current_active_avatar_frames, _avatar_frames_map, _avatar_frames_lock
    global _bouncing_enabled, BOUNCING_MAX_OFFSET_PIXELS, _bouncing_active, _bouncing_start_time, _original_background_fps, CAM_FPS

    _cam_loop_running = True
    # print("DEBUG (start_frame_sending_loop): Запущен асинхронный цикл генерации кадров.") # УДАЛЕНО

    while _cam_loop_running:
        current_bounce_offset = 0  # Смещение по умолчанию

        # --- Логика расчета смещения для разового подпрыгивания ---
        if _bouncing_active and _bouncing_enabled:
            elapsed_ms = (time.time() - _bouncing_start_time) * 1000
            if elapsed_ms >= BOUNCING_DURATION_MS:
                _bouncing_active = False  # Завершаем анимацию
                current_bounce_offset = 0
                # print("DEBUG (start_frame_sending_loop): Bouncing animation ended.") # УДАЛЕНО
            else:
                progress = elapsed_ms / BOUNCING_DURATION_MS
                # Используем math.sin(progress * math.pi) для одного "всплеска" от 0 до 1, затем обратно до 0.
                # Умножаем на -BOUNCING_MAX_OFFSET_PIXELS для движения вверх.
                current_bounce_offset = -BOUNCING_MAX_OFFSET_PIXELS * math.sin(progress * math.pi)
                # print(f"DEBUG (start_frame_sending_loop): Bouncing offset: {current_bounce_offset:.2f} (progress: {progress:.2f})") # УДАЛЕНО

        # Всю логику композиции и отправки кадра лучше держать внутри одного блока try-except
        try:
            composed_frame_rgb = None  # Инициализируем для обеспечения доступности

            with _avatar_frames_lock:
                active_avatar_data = _current_active_avatar_frames
                current_avatar_frames_actual = active_avatar_data.get('frames', [])
                original_avatar_fps = active_avatar_data.get('original_fps', CAM_FPS)  # Fallback to CAM_FPS

                # --- Обработка фонового кадра ---
                # Проверяем, что _background_frames_list не пуст перед использованием len()
                if _background_frames_list:
                    background_frame_advance_factor = _original_background_fps / CAM_FPS
                    _current_background_frame_float_index = (
                                                                        _current_background_frame_float_index + background_frame_advance_factor) % len(
                        _background_frames_list)
                    background_idx_to_use = int(math.floor(_current_background_frame_float_index))
                    _current_background_frame_index = background_idx_to_use  # Обновляем целочисленный индекс фона
                else:
                    background_idx_to_use = 0  # Если фон пуст, используем 0 или запасной вариант
                    print("ПРЕДУПРЕЖДЕНИЕ: Список фоновых кадров пуст. Используется индекс 0.")

                if current_avatar_frames_actual:  # Если есть кадры аватара для композиции
                    # Рассчитываем, насколько нужно продвинуться по кадрам GIF за один кадр камеры
                    frame_advance_factor = original_avatar_fps / CAM_FPS

                    # Обновляем плавающий индекс
                    _current_avatar_frame_float_index = (
                                                                    _current_avatar_frame_float_index + frame_advance_factor) % len(
                        current_avatar_frames_actual)

                    # Получаем целочисленный индекс для использования в композиции
                    avatar_idx_to_use = int(math.floor(_current_avatar_frame_float_index))

                    composed_frame_rgb = _compose_frame(background_idx_to_use,  # Используем вычисленный индекс фона
                                                        avatar_idx_to_use,
                                                        current_avatar_frames_actual,
                                                        # Передаем актуальный список кадров
                                                        y_offset_addition=current_bounce_offset)

                    # Обновляем целочисленный индекс (для совместимости/отладки)
                    _current_avatar_frame_index = avatar_idx_to_use
                else:  # Если активных кадров аватара нет, пробуем запасной вариант 'Молчит'
                    print(
                        "ПРЕДУПРЕЖДЕНИЕ (start_frame_sending_loop): Нет активных кадров аватара. Использую запасной вариант 'Молчит'.")
                    fallback_data = _avatar_frames_map.get("Молчит", {"frames": [], "original_fps": CAM_FPS})
                    fallback_frames = fallback_data['frames']
                    fallback_original_fps = fallback_data['original_fps']

                    if fallback_frames:
                        fallback_frame_advance_factor = fallback_original_fps / CAM_FPS
                        _current_avatar_frame_float_index = (
                                                                        _current_avatar_frame_float_index + fallback_frame_advance_factor) % len(
                            fallback_frames)
                        fallback_idx_to_use = int(math.floor(_current_avatar_frame_float_index))

                        composed_frame_rgb = _compose_frame(background_idx_to_use,  # Используем вычисленный индекс фона
                                                            fallback_idx_to_use,  # Используем вычисленный индекс
                                                            fallback_frames,
                                                            y_offset_addition=current_bounce_offset)  # Применяем смещение и к запасному
                        _current_avatar_frame_index = fallback_idx_to_use  # Обновляем целочисленный индекс
                    else:
                        print(
                            "КРИТИЧЕСКОЕ ПРЕДУПРЕЖДЕНИЕ: Нет доступных кадров ни для текущего статуса, ни для 'Молчит'. Анимация аватара будет пустой.")
                        # composed_frame_rgb останется None.

            # Отправляем скомпонованный кадр
            if composed_frame_rgb is not None:
                try:
                    virtual_cam_obj.send(composed_frame_rgb)
                    virtual_cam_obj.sleep_until_next_frame()

                    # Помещаем кадр в очередь для GUI
                    try:
                        while not display_queue.empty():
                            display_queue.get_nowait()
                        display_queue.put_nowait(composed_frame_rgb)
                    except queue.Full:
                        pass
                except Exception as e:
                    print(f"ОШИБКА отправки кадра в виртуальную камеру или GUI: {e}")
                    _cam_loop_running = False
            else:
                if _background_frames_list:
                    background_frame_to_send = _background_frames_list[background_idx_to_use]
                    virtual_cam_obj.send(background_frame_to_send)
                    virtual_cam_obj.sleep_until_next_frame()
                    try:
                        while not display_queue.empty():
                            display_queue.get_nowait()
                        display_queue.put_nowait(background_frame_to_send)
                    except queue.Full:
                        pass
                else:
                    black_frame = np.zeros((CAM_HEIGHT, CAM_WIDTH, 3), dtype=np.uint8)
                    virtual_cam_obj.send(black_frame)
                    virtual_cam_obj.sleep_until_next_frame()
                    try:
                        while not display_queue.empty():
                            display_queue.get_nowait()
                        display_queue.put_nowait(black_frame)
                    except queue.Full:
                        pass

        except Exception as e:
            print(f"ОШИБКА в цикле генерации кадров: {e}")
            await asyncio.sleep(1)


def voice_status_callback(status_message: str, debug_message: str):
    """
    Эта функция вызывается при каждом изменении статуса голоса.
    Она обновляет набор кадров аватара для отображения и выводит статус в консоль.
    """
    global _current_active_avatar_frames, _current_avatar_frame_index, _current_avatar_frame_float_index
    global _status_change_listener, _avatar_frames_lock, _avatar_frames_map
    global _bouncing_active, _bouncing_start_time, _bouncing_enabled, _last_known_voice_status

    # Вызываем слушателя статуса, если он установлен.
    if _status_change_listener:
        _status_change_listener(status_message, debug_message)

    with _avatar_frames_lock:
        # Пытаемся получить данные о кадрах для текущего статуса
        new_active_avatar_data = _avatar_frames_map.get(status_message, {"frames": [], "original_fps": CAM_FPS})

        if new_active_avatar_data['frames']:
            if new_active_avatar_data is not _current_active_avatar_frames:
                _current_active_avatar_frames = new_active_avatar_data
                _current_avatar_frame_index = 0
                _current_avatar_frame_float_index = 0.0
                # print(f"DEBUG (voice_status_callback): Активные кадры аватара изменены на '{status_message}'.") # УДАЛЕНО

            # --- Логика запуска анимации подпрыгивания ---
            # Запускаем анимацию, если статус меняется на "Говорит",
            # и она еще не активна, и функция подпрыгивания включена.
            if (status_message == "Говорит" and
                    _bouncing_enabled and
                    not _bouncing_active):

                # Дополнительная проверка, чтобы запускать только при переходе "Молчит" -> "Говорит"
                # или если это первое "Говорит" после запуска
                if _last_known_voice_status != "Говорит":
                    _bouncing_active = True
                    _bouncing_start_time = time.time()
                    # print("DEBUG (voice_status_callback): Анимация подпрыгивания активирована (статус Говорит).") # УДАЛЕНО

            # Обновляем _last_known_voice_status
            _last_known_voice_status = status_message

        else:
            # Если для полученного статуса нет кадров, используем запасной вариант 'Молчит'.
            fallback_data = _avatar_frames_map.get("Молчит", {"frames": [], "original_fps": CAM_FPS})
            fallback_frames = fallback_data['frames']
            if fallback_data is not _current_active_avatar_frames:
                _current_active_avatar_frames = fallback_data
                _current_avatar_frame_index = 0
                _current_avatar_frame_float_index = 0.0
                print(
                    f"ПРЕДУПРЕЖДЕНИЕ (voice_status_callback): Кадры для статуса '{status_message}' не найдены. Использую запасной вариант 'Молчит' ({len(fallback_frames)} кадров).")
            else:
                # print(f"DEBUG (voice_status_callback): Кадры для статуса '{status_message}' не найдены, но аватар уже отображает 'Молчит'.") # УДАЛЕНО
                pass  # Просто пропускаем, если статус не меняется

            if not fallback_frames:
                print(
                    "КРИТИЧЕСКОЕ ПРЕДУПРЕЖДЕНИЕ: Нет доступных кадров ни для текущего статуса, ни для 'Молчит'. Анимация аватара будет пустой.")


def shutdown_virtual_camera():
    """Закрывает объект виртуальной камеры и останавливает цикл отправки кадров."""
    global virtual_cam_obj, _cam_loop_running

    _cam_loop_running = False
    # print("DEBUG (shutdown_virtual_camera): Флаг _cam_loop_running установлен в False.") # УДАЛЕНО

    if virtual_cam_obj and virtual_cam_obj is not False:
        print("Закрытие виртуальной камеры...")
        virtual_cam_obj.close()
        virtual_cam_obj = None
        print("Виртуальная камера закрыта.")


# Этот блок будет выполнен только при прямом запуске virtual_camera.py,
# а не при импорте.
if __name__ == '__main__':
    # Пример использования (для тестирования)
    print("Запуск virtual_camera.py напрямую для тестирования...")
    # Здесь можно добавить тестовую логику, например, вызов initialize_virtual_camera()
    # и запуск send_frames_loop_asyncio в отдельном потоке
    pass
