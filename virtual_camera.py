import sys
import os
import cv2  # Импортируем OpenCV для работы с изображениями
import numpy as np  # Импортируем NumPy, так как OpenCV использует массивы NumPy
import pyvirtualcam  # Импортируем библиотеку для создания виртуальной камеры
import queue  # Импортируем модуль queue для создания очереди кадров
from PIL import Image, ImageSequence  # Для работы с GIF и PNG
import asyncio  # Импортируем asyncio для await
import threading  # Импортируем threading для использования Lock

# --- КОНФИГУРАЦИЯ ПУТЕЙ ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Папка для всех обработанных аватаров и статических изображений (фона, оверлеев)
# Это папка, с которой работает пользователь.
AVATAR_ASSETS_FOLDER = os.path.join(SCRIPT_DIR, "reactive_avatar")

# Глобальные переменные для размеров и FPS камеры (размеры будут определены динамически)
CAM_WIDTH = 0
CAM_HEIGHT = 0
CAM_FPS = 30  # FPS остается фиксированным

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
_avatar_frames_map = {}  # Словарь: "статус" -> список NumPy массивов (RGBA) кадров аватара

# Индексы текущих кадров для анимации
_current_avatar_frame_index = 0
_current_background_frame_index = 0

# Текущий активный набор кадров аватара (устанавливается voice_status_callback)
_current_active_avatar_frames = []
# Добавляем блокировку для потокобезопасного доступа к _current_active_avatar_frames
_avatar_frames_lock = threading.Lock()

# Флаг для управления циклом отправки кадров
_cam_loop_running = False

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
    Возвращает список NumPy массивов (RGBA для аватаров, RGB для фона).
    """
    gif_path = os.path.join(AVATAR_ASSETS_FOLDER, f"{base_name}.gif")
    png_path = os.path.join(AVATAR_ASSETS_FOLDER, f"{base_name}.png")
    frames = []

    file_to_load = None
    if os.path.exists(gif_path):
        file_to_load = gif_path
    elif os.path.exists(png_path):
        file_to_load = png_path
    else:
        print(f"  ПРЕДУПРЕЖДЕНИЕ: Ни GIF, ни PNG файл не найден для '{base_name}'. Возвращаю пустой список кадров.")
        return []

    try:
        if file_to_load.endswith(".gif"):
            with Image.open(file_to_load) as im:
                for frame in ImageSequence.Iterator(im):
                    if is_avatar:
                        frames.append(np.array(frame.convert("RGBA")))
                    else:
                        frames.append(np.array(frame.convert("RGB")))
        else:  # PNG
            with Image.open(file_to_load) as im:
                if is_avatar:
                    frames.append(np.array(im.convert("RGBA")))
                else:
                    frames.append(np.array(im.convert("RGB")))
    except Exception as e:
        print(f"  ОШИБКА: Не удалось загрузить кадры из '{file_to_load}': {e}")
        return []
    return frames


def initialize_virtual_camera():
    """
    Инициализирует объект виртуальной камеры pyvirtualcam и предварительно загружает все изображения.
    Эта функция вызывается только один раз из main_script.py.
    """
    global virtual_cam_obj, CAM_WIDTH, CAM_HEIGHT
    global _background_frames_list, _avatar_frames_map, _current_active_avatar_frames, _avatar_frames_lock

    if virtual_cam_obj is not None and virtual_cam_obj is not False:
        print("Виртуальная камера уже инициализирована.")
        return

    print("\n--- Предварительная загрузка изображений и анимаций ---")
    _background_frames_list = _load_frames_from_file(BACKGROUND_IMAGE_PATH, is_avatar=False)
    if not _background_frames_list:
        print("КРИТИЧЕСКАЯ ОШИБКА: Не удалось загрузить фоновое изображение. Не могу инициализировать камеру.")
        virtual_cam_obj = False
        return

    # Определяем размеры камеры по первому кадру фона
    CAM_HEIGHT, CAM_WIDTH, _ = _background_frames_list[0].shape
    print(f"Разрешение камеры установлено по фону: {CAM_WIDTH}x{CAM_HEIGHT} @ {CAM_FPS} FPS.")

    for status, filename in STATUS_TO_FILENAME_MAP.items():
        _avatar_frames_map[status] = _load_frames_from_file(filename, is_avatar=True)
        if not _avatar_frames_map[status]:
            print(f"ПРЕДУПРЕЖДЕНИЕ: Не удалось загрузить аватар для статуса '{status}'. Использую пустой набор кадров.")

    # Диагностический вывод после загрузки всех аватаров
    print("DEBUG (initialize_virtual_camera): Содержимое _avatar_frames_map после загрузки:")
    for status, frames in _avatar_frames_map.items():
        print(f"  Статус '{status}' (файл '{STATUS_TO_FILENAME_MAP.get(status, 'N/A')}'): {len(frames)} кадров")

    # Добавлено для отладки
    molchit_frames_init_len = len(_avatar_frames_map.get("Молчит", []))
    print(
        f"DEBUG (initialize_virtual_camera): До установки _current_active_avatar_frames: 'Молчит' имеет {molchit_frames_init_len} кадров.")

    # Устанавливаем начальный активный аватар (например, "Молчит")
    with _avatar_frames_lock:
        _current_active_avatar_frames = _avatar_frames_map.get("Молчит", [])
        _current_avatar_frame_index = 0
    print(
        f"DEBUG (initialize_virtual_camera): Начальный активный аватар 'Молчит' имеет {len(_current_active_avatar_frames)} кадров (после блокировки).")

    try:
        print(f"Инициализация виртуальной камеры: {CAM_WIDTH}x{CAM_HEIGHT} @ {CAM_FPS} FPS...")
        virtual_cam_obj = pyvirtualcam.Camera(width=CAM_WIDTH, height=CAM_HEIGHT, fps=CAM_FPS, print_fps=False)
        print("Виртуальная камера успешно инициализирована.")

        # Получаем первый кадр для инициализации
        initial_avatar_frames = _avatar_frames_map.get("Молчит", [])
        if not initial_avatar_frames:
            initial_avatar_frames = [
                np.zeros((200, 200, 4), dtype=np.uint8)]  # Если даже "Молчит" пуст, используем пустой черный квадрат
            print("ПРЕДУПРЕЖДЕНИЕ: Нет кадров для 'Молчит' при инициализации. Использую заглушку.")

        # Композируем первый кадр для инициализации GUI
        initial_frame = _compose_frame(0, 0, initial_avatar_frames)
        virtual_cam_obj.send(initial_frame)
        virtual_cam_obj.sleep_until_next_frame()

    except Exception as e:
        print(f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось инициализировать виртуальную камеру: {e}")
        print(
            "Пожалуйста, убедитесь, что у вас установлен драйвер виртуальной камеры (например, OBS Virtual Camera) и вы запустили 'pip install pyvirtualcam opencv-python Pillow'.")
        virtual_cam_obj = False


def _compose_frame(bg_frame_idx: int, avatar_frame_idx: int, avatar_frames: list[np.ndarray]) -> np.ndarray:
    """
    Композирует текущий кадр фона и заданный кадр аватара.
    Возвращает NumPy массив RGB для отправки в виртуальную камеру.
    """
    global _background_frames_list, CAM_WIDTH, CAM_HEIGHT

    if CAM_WIDTH == 0 or CAM_HEIGHT == 0 or not _background_frames_list:
        print(
            "ПРЕДУПРЕЖДЕНИЕ (_compose_frame): Размеры камеры не определены или фон не загружен. Возвращаю черный кадр.")
        return np.zeros((480, 640, 3), dtype=np.uint8)

    background_frame_rgb = _background_frames_list[bg_frame_idx % len(_background_frames_list)].copy()

    if not avatar_frames:
        print(f"ПРЕДУПРЕЖДЕНИЕ (_compose_frame): Получен пустой список кадров аватара. Возвращаю только фон.")
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
        print(
            "ПРЕДУПРЕЖДЕНИЕ (_compose_frame): Размер аватара после масштабирования стал нулевым или отрицательным. Возвращаю только фон.")
        return background_frame_rgb

    avatar_resized = cv2.resize(avatar_frame_rgba, (new_avatar_w, new_avatar_h), interpolation=cv2.INTER_AREA)

    x_offset = (CAM_WIDTH - new_avatar_w) // 2
    y_offset = (CAM_HEIGHT - new_avatar_h) // 2

    avatar_rgb_float = avatar_resized[:, :, :3].astype(np.float32)
    alpha_channel_float = avatar_resized[:, :, 3].astype(np.float32) / 255.0
    alpha_factor_3_chan = cv2.merge([alpha_channel_float, alpha_channel_float, alpha_channel_float])

    y1, y2 = y_offset, y_offset + new_avatar_h
    x1, x2 = x_offset, x_offset + new_avatar_w

    y2 = min(y2, CAM_HEIGHT)
    x2 = min(x2, CAM_WIDTH)
    y1 = max(0, y1)
    x1 = max(0, x1)

    actual_h = y2 - y1
    actual_w = x2 - x1

    if actual_h <= 0 or actual_w <= 0:
        print(
            "ПРЕДУПРЕЖДЕНИЕ (_compose_frame): Фактическая область для наложения нулевая или отрицательная. Возвращаю только фон.")
        return background_frame_rgb

    avatar_rgb_clipped = avatar_rgb_float[0:actual_h, 0:actual_w]
    alpha_factor_clipped = alpha_factor_3_chan[0:actual_h, 0:actual_w]

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
    avatar_frames_for_preview = _avatar_frames_map.get(current_status, [])
    if not avatar_frames_for_preview:
        avatar_frames_for_preview = _avatar_frames_map.get("Молчит", [])
        print(
            f"ПРЕДУПРЕЖДЕНИЕ (get_static_preview_frame): Кадры для статуса '{current_status}' не найдены. Использую 'Молчит' ({len(avatar_frames_for_preview)} кадров) для предпросмотра.")

    # Композируем первый кадр для предпросмотра
    preview_frame = _compose_frame(0, 0, avatar_frames_for_preview)
    print(f"DEBUG (get_static_preview_frame): Возвращаю статичный кадр предпросмотра для статуса '{current_status}'.")
    return preview_frame


async def start_frame_sending_loop():
    """
    Асинхронный цикл, который постоянно генерирует и отправляет кадры в виртуальную камеру.
    Эта функция предполагает, что виртуальная камера уже инициализирована.
    """
    global _current_avatar_frame_index, _current_background_frame_index
    global _cam_loop_running, display_queue, virtual_cam_obj, _current_active_avatar_frames, _avatar_frames_map, _avatar_frames_lock

    _cam_loop_running = True
    print("DEBUG (start_frame_sending_loop): Запущен асинхронный цикл отправки кадров.")

    # В этом цикле больше не будет принудительного использования анимации "Говорит".
    # Он будет полагаться на _current_active_avatar_frames, установленный voice_status_callback.
    # Примечание: Начальное значение _current_active_avatar_frames устанавливается в initialize_virtual_camera.
    # Если _current_active_avatar_frames окажется пустым здесь (что не должно произойти, если initialize_virtual_camera
    # и voice_status_callback работают корректно), будет использован запасной вариант "Молчит".

    while _cam_loop_running:
        if virtual_cam_obj is False or CAM_WIDTH == 0 or CAM_HEIGHT == 0:
            print("DEBUG (start_frame_sending_loop): Виртуальная камера не готова, ожидаю...")
            await asyncio.sleep(1)
            continue

        if not _background_frames_list:
            print("DEBUG (start_frame_sending_loop): Нет фоновых кадров для отправки. Ожидаю...")
            await asyncio.sleep(1)
            continue

        try:
            # Получаем текущие кадры аватара и индекс под блокировкой
            with _avatar_frames_lock:
                current_avatar_frames_for_compose = _current_active_avatar_frames
                current_avatar_frame_idx_for_compose = _current_avatar_frame_index

                # Если текущие активные кадры пусты (что указывает на проблему,
                # так как voice_status_callback должен был их установить), используем запасную.
                if not current_avatar_frames_for_compose:
                    print(
                        "ПРЕДУПРЕЖДЕНИЕ (start_frame_sending_loop): Нет активных кадров аватара для композиции. Использую запасной вариант 'Молчит'.")
                    current_avatar_frames_for_compose = _avatar_frames_map.get("Молчит", [])
                    # Если даже запасной вариант пуст, то мы не сможем ничего отобразить
                    if not current_avatar_frames_for_compose:
                        print(
                            "КРИТИЧЕСКОЕ ПРЕДУПРЕЖДЕНИЕ: Нет доступных кадров для 'Говорит' или 'Молчит'. Анимация аватара будет пустой.")
                        await asyncio.sleep(1)  # Короткая пауза, чтобы избежать бесконечного цикла ошибок
                        continue
                    current_avatar_frame_idx_for_compose = 0  # Сбрасываем индекс для запасного варианта

                # Композируем кадр, передавая явный список кадров аватара
                composed_frame_rgb = _compose_frame(_current_background_frame_index,
                                                    current_avatar_frame_idx_for_compose,
                                                    current_avatar_frames_for_compose)

                # Обновляем индексы для следующего кадра (циклическая анимация)
                _current_background_frame_index = (_current_background_frame_index + 1) % len(_background_frames_list)

                # Обновляем индекс аватара только если список кадров не пуст
                if current_avatar_frames_for_compose:
                    _current_avatar_frame_index = (current_avatar_frame_idx_for_compose + 1) % len(
                        current_avatar_frames_for_compose)
                else:
                    _current_avatar_frame_index = 0  # Сбрасываем, если по какой-то причине оказался пуст

            # Отправляем кадр в виртуальную камеру
            virtual_cam_obj.send(composed_frame_rgb)

            # Помещаем кадр в очередь для отображения в GUI
            try:
                if not display_queue.empty():
                    display_queue.get_nowait()
                display_queue.put_nowait(composed_frame_rgb)
            except queue.Full:
                pass

            # Wait until the next frame to maintain FPS
            virtual_cam_obj.sleep_until_next_frame()

        except Exception as e:
            print(f"ОШИБКА в цикле отправки кадров: {e}")
            await asyncio.sleep(1)


def voice_status_callback(status_message: str, debug_message: str):
    """
    Эта функция вызывается при каждом изменении статуса голоса.
    Она обновляет набор кадров аватара для отображения и выводит статус в консоль.
    """
    global _current_active_avatar_frames, _current_avatar_frame_index
    global _status_change_listener, _avatar_frames_lock, _avatar_frames_map

    # Вызываем слушателя статуса, если он установлен.
    if _status_change_listener:
        _status_change_listener(status_message, debug_message)
    # --- ПРИНУДИТЕЛЬНО УСТАНАВЛИВАЕМ АНИМАЦИЮ "ГОВОРИТ" ДЛЯ ТЕСТИРОВАНИЯ ---
    # Этот блок будет принудительно устанавливать анимацию "Говорит" при любом изменении статуса.
    # Если анимация "Говорит" отсутствует, будет использован запасной вариант "Молчит".
    with _avatar_frames_lock:
        # Пытаемся получить кадры для текущего статуса
        new_active_frames = _avatar_frames_map.get(status_message, [])

        if new_active_frames: # Если найдены кадры для текущего статуса
            if new_active_frames is not _current_active_avatar_frames: # Если набор кадров изменился
                _current_active_avatar_frames = new_active_frames
                _current_avatar_frame_index = 0 # Сбрасываем индекс при смене анимации
            #     print(
            #         f"DEBUG (voice_status_callback): Аватар обновлен на '{status_message}' ({len(_current_active_avatar_frames)} кадров).")
            # else:
            #     # Если статус тот же и набор кадров не изменился, просто продолжаем текущую анимацию.
            #     print(
            #         f"DEBUG (voice_status_callback): Статус '{status_message}' получен, но аватар не изменился. Продолжаю текущую анимацию.")
        else:
            # Если для полученного статуса нет кадров, используем запасной вариант 'Молчит'.
            fallback_frames = _avatar_frames_map.get("Молчит", [])
            if fallback_frames is not _current_active_avatar_frames: # Избегаем ненужных обновлений
                _current_active_avatar_frames = fallback_frames
                _current_avatar_frame_index = 0
                print(
                    f"ПРЕДУПРЕЖДЕНИЕ (voice_status_callback): Кадры для статуса '{status_message}' не найдены. Использую запасной вариант 'Молчит' ({len(_current_active_avatar_frames)} кадров).")
            else:
                 print(
                    f"DEBUG (voice_status_callback): Кадры для статуса '{status_message}' не найдены, но аватар уже отображает 'Молчит'.")

            if not fallback_frames: # Крайний случай: даже 'Молчит' кадры отсутствуют
                print(
                    "КРИТИЧЕСКОЕ ПРЕДУПРЕЖДЕНИЕ: Нет доступных кадров ни для текущего статуса, ни для 'Молчит'. Анимация аватара будет пустой.")
    # --- КОНЕЦ ДЛЯ ТЕСТИРОВАНИЯ ---


def shutdown_virtual_camera():
    """Закрывает объект виртуальной камеры и останавливает цикл отправки кадров."""
    global virtual_cam_obj, _cam_loop_running
    _cam_loop_running = False
    if virtual_cam_obj and virtual_cam_obj is not False:
        print("Закрытие виртуальной камеры...")
        virtual_cam_obj.close()
        virtual_cam_obj = None
        print("Виртуальная камера закрыта.")
