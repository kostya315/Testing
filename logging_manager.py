import sys
import os
import datetime
import threading

# Объявляем глобальную переменную для объекта-перенаправителя, чтобы его можно было получить
_global_log_redirector = None


class LoggerRedirector:
    """
    Перенаправляет sys.stdout и sys.stderr в файл журнала.
    Сохраняет текущий вывод в 'latest.log' и создает ежедневные архивы.
    """

    def __init__(self, log_dir="logs"):
        self.log_dir = log_dir
        # Определяем базовую директорию для логов.
        # Если приложение скомпилировано PyInstaller, sys._MEIPASS указывает на временную папку.
        # В этом случае, мы хотим, чтобы логи писались рядом с основным исполняемым файлом.
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            # Когда запущен как exe, sys.argv[0] - это путь к exe
            base_path = os.path.dirname(sys.argv[0])
        else:
            # Когда запущен как скрипт
            base_path = os.path.dirname(os.path.abspath(__file__))

        self.full_log_dir = os.path.join(base_path, log_dir)
        os.makedirs(self.full_log_dir, exist_ok=True)

        self.stdout = sys.stdout
        self.stderr = sys.stderr
        self.log_file = None
        self.latest_log_path = os.path.join(self.full_log_dir, "latest.log")
        self.lock = threading.Lock()  # Для потокобезопасной записи

        self._open_new_log_file()

    def _open_new_log_file(self):
        """Открывает новый файл журнала с временной меткой и обрабатывает rotation."""
        if self.log_file and not self.log_file.closed:
            self.log_file.close()

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.current_log_path = os.path.join(self.full_log_dir, f"{timestamp}.log")

        try:
            # Сначала перемещаем старый latest.log в файл с временной меткой, если он существует
            if os.path.exists(self.latest_log_path):
                # Если файл с таким timestamp уже существует (очень маловероятно, но на всякий случай)
                if os.path.exists(self.current_log_path):
                    os.remove(self.current_log_path)
                os.rename(self.latest_log_path, self.current_log_path)

            # Открываем новый latest.log для записи
            self.log_file = open(self.latest_log_path, 'a', encoding='utf-8')
            # Также записываем в новый файл с timestamp для сохранения истории
            self._archive_file = open(self.current_log_path, 'a', encoding='utf-8')

        except Exception as e:
            # Если не удалось открыть файл журнала, выводим ошибку в исходную консоль
            if self.stdout:
                self.stdout.write(f"ОШИБКА: Не удалось открыть файл журнала: {e}\n")
            self.log_file = None  # Устанавливаем None, чтобы предотвратить дальнейшие попытки записи в несуществующий файл
            self._archive_file = None

    def write(self, message):
        """Пишет сообщение в файл журнала и, опционально, в исходную консоль."""
        with self.lock:
            # Всегда пишем в 'latest.log'
            if self.log_file and not self.log_file.closed:
                self.log_file.write(message)
                self.log_file.flush()  # Немедленно сбрасываем буфер

            # Также пишем в архивный файл (если он открыт)
            if self._archive_file and not self._archive_file.closed:
                self._archive_file.write(message)
                self._archive_file.flush()  # Немедленно сбрасываем буфер

            # Если мы запускаемся не как exe и хотим видеть вывод в консоли во время разработки,
            # можно раскомментировать следующую строку:
            # if not getattr(sys, 'frozen', False) and self.stdout:
            #     self.stdout.write(message)
            #     self.stdout.flush()

    def flush(self):
        """Метод flush требуется для совместимости со стандартными потоками."""
        if self.log_file and not self.log_file.closed:
            self.log_file.flush()
        if self._archive_file and not self._archive_file.closed:
            self._archive_file.flush()
        # Если мы выводим в оригинальный stdout (например, при разработке), также сбрасываем его
        # if not getattr(sys, 'frozen', False) and self.stdout:
        #     self.stdout.flush()

    def close(self):
        """Закрывает все открытые файлы журнала."""
        with self.lock:
            if self.log_file and not self.log_file.closed:
                self.log_file.close()
                self.log_file = None
            if self._archive_file and not self._archive_file.closed:
                self._archive_file.close()
                self._archive_file = None


def setup_logging():
    """
    Настраивает перенаправление sys.stdout и sys.stderr в LoggerRedirector.
    Должен быть вызван один раз в начале приложения.
    """
    global _global_log_redirector
    if _global_log_redirector is None:
        _global_log_redirector = LoggerRedirector()
        sys.stdout = _global_log_redirector
        sys.stderr = _global_log_redirector
        # sys.excepthook = handle_exception # Можно добавить свой обработчик исключений, если нужно
        print(
            f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] --- Логирование перенаправлено в '{_global_log_redirector.full_log_dir}' ---")
    else:
        print("Логирование уже настроено.")


def get_log_redirector() -> LoggerRedirector | None:
    """Возвращает текущий экземпляр LoggerRedirector."""
    return _global_log_redirector


def handle_exception(exc_type, exc_value, exc_traceback):
    """
    Кастомный обработчик неперехваченных исключений.
    Перенаправляет исключения в лог-файл.
    """
    if issubclass(exc_type, KeyboardInterrupt):
        # Не вмешиваемся в KeyboardInterrupt, чтобы Ctrl+C работал
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    # Записываем исключение в лог-файл
    log_message = f"Неперехваченное исключение:\n"
    import traceback
    log_message += "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))

    if _global_log_redirector:
        _global_log_redirector.write(log_message)
    else:
        # Если логгирование еще не настроено, выводим в оригинальный stderr
        sys.__stderr__.write(log_message)

    # Можно также показать QMessageBox для пользователя, если это GUI-приложение
    # from PyQt5.QtWidgets import QApplication, QMessageBox
    # app = QApplication.instance()
    # if app:
    #     QMessageBox.critical(None, "Ошибка приложения", "Произошла критическая ошибка. Подробности в лог-файле.")
    # else:
    #     print("Критическая ошибка: Приложение не GUI, не удалось показать сообщение.")

