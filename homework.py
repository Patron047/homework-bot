import logging
import os
import sys
import time

from dotenv import load_dotenv
import requests
from telebot import TeleBot

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger(__name__)

load_dotenv()

PRACTICUM_TOKEN = os.getenv('ya_id')
TELEGRAM_TOKEN = os.getenv('tg_token')
TELEGRAM_CHAT_ID = os.getenv('tg_chat_id')

RETRY_PERIOD = 600
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}

HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.'
}


def check_tokens():
    """Проверяет доступность переменных окружения."""
    tokens = {
        'PRACTICUM_TOKEN': PRACTICUM_TOKEN,
        'TELEGRAM_TOKEN': TELEGRAM_TOKEN,
        'TELEGRAM_CHAT_ID': TELEGRAM_CHAT_ID,
    }
    for name, value in tokens.items():
        if not value:
            logger.critical(
                f'Отсутствует обязательная переменная окружения: {name}'
            )
            raise ValueError(
                f'Отсутствует обязательная переменная окружения: {name}'
            )
    return True


def send_message(bot, message):
    """Отправляет сообщение в Telegram-чат."""
    try:
        bot.send_message(TELEGRAM_CHAT_ID, message)
        logger.debug(f'Бот отправил сообщение "{message}"')
    except Exception as error:
        logger.error(f'Сбой при отправке сообщения в Telegram: {error}')
        raise


def get_api_answer(timestamp):
    """Делает запрос к единственному эндпоинту API-сервиса."""
    params = {'from_date': timestamp}
    try:
        response = requests.get(ENDPOINT, headers=HEADERS, params=params)
        if response.status_code != 200:
            logger.error(
                'Недоступность эндпоинта %s. Код ответа: %s',
                ENDPOINT,
                response.status_code
            )
            raise requests.HTTPError(
                f'HTTP ошибка при запросе: {response.status_code}'
            )
        return response.json()
    except requests.RequestException as error:
        logger.error(f'Сбой при запросе к эндпоинту {ENDPOINT}: {error}')
        raise ValueError(f'Ошибка соединения: {error}') from error
    except requests.exceptions.JSONDecodeError as error:
        logger.error('Ошибка декодирования JSON в ответе API')
        raise ValueError(f'Ошибка декодирования JSON: {error}') from error


def check_response(response):
    """Проверяет ответ API на соответствие документации."""
    if not isinstance(response, dict):
        logger.error('Ответ API не является словарем')
        raise TypeError('Ответ API не является словарем')
    if 'homeworks' not in response:
        logger.error('В ответе API отсутствует ключ "homeworks"')
        raise KeyError('В ответе API отсутствует ключ "homeworks"')
    if not isinstance(response['homeworks'], list):
        logger.error('Значение ключа "homeworks" не является списком')
        raise TypeError('Значение ключа "homeworks" не является списком')
    return response['homeworks']


def parse_status(homework):
    """
    Извлекает из информации о конкретной домашней работе статус этой работы.
    Проверяет наличие статуса в словаре вердиктов и формирует сообщение.
    """
    if 'homework_name' not in homework:
        logger.error('В ответе API отсутствует ключ "homework_name"')
        raise KeyError('В ответе API отсутствует ключ "homework_name"')
    homework_name = homework['homework_name']
    homework_status = homework.get('status')
    if homework_status not in HOMEWORK_VERDICTS:
        logger.error(f'Неожиданный статус домашней работы: {homework_status}')
        raise ValueError(f'Неизвестный статус работы: {homework_status}')
    verdict = HOMEWORK_VERDICTS[homework_status]
    return f'Изменился статус проверки работы "{homework_name}". {verdict}'


def process_homeworks(bot, homeworks):
    """Обрабатывает список домашних работ и отправляет уведомления."""
    for homework in homeworks:
        try:
            message = parse_status(homework)
            send_message(bot, message)
        except ValueError:
            continue


def handle_error(error, bot, last_error_message):
    """Обрабатывает возникшее исключение: логирует и отправляет уведомление."""
    current_error = str(error)
    message = f'Сбой в работе программы: {error}'
    logger.error(message)
    if current_error != last_error_message:
        try:
            send_message(bot, message)
        except Exception:
            pass
        last_error_message = current_error
    else:
        logger.debug('Повторяющаяся ошибка сообщение в Telegram не отправлено')
    return last_error_message, True


def main():
    """Основная логика работы бота."""
    try:
        check_tokens()
    except ValueError:
        logger.critical('Программа принудительно остановлена.')
        return
    bot = TeleBot(token=TELEGRAM_TOKEN)
    timestamp = int(time.time())
    last_error_message = None
    while True:
        try:
            response = get_api_answer(timestamp)
            homeworks = check_response(response)
            timestamp = response.get('current_date', timestamp)
            if not homeworks:
                logger.debug('Отсутствие в ответе новых статусов')
            else:
                process_homeworks(bot, homeworks)
            last_error_message = None
        except Exception as error:
            result = handle_error(error, bot, last_error_message)
            last_error_message, should_continue = result
            if not should_continue:
                break
        time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    main()
