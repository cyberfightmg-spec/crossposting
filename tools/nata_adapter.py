"""
Content Adapter - стиль Наты Анарбаевой
Переписывает текст в стиле "маркетинг для взрослых"
"""
import os
from typing import Optional

def adapt_nata_style(text: str) -> str:
    """
    Переписывает текст в стиле Наты Анарбаевой (Hi, beauty!).
    
    Стиль: прямой, жёсткий, честный. Маркетинг — это бой.
    """
    
    # Если текст короткий, возвращаем как есть
    if len(text) < 50:
        return text
    
    # Разбиваем на абзацы
    paragraphs = [p.strip() for p in text.split('\n') if p.strip()]
    
    if not paragraphs:
        return text
    
    # Берём основной контент (первые 2-3 абзаца)
    main_content = paragraphs[:3]
    
    # Извлекаем суть
    core_message = ' '.join(main_content)
    
    # Убираем вводные слова и смайлики
    cleaned = _clean_text(core_message)
    
    # Создаём текст в стиле Наты
    adapted = _rewrite_in_nata_style(cleaned)
    
    return adapted


def _clean_text(text: str) -> str:
    """Очищает текст от лишнего"""
    import re
    
    # Убираем смайлики (оставляем максимум 1-2)
    emoji_pattern = re.compile("["
        u"\U0001F600-\U0001F64F"  # emoticons
        u"\U0001F300-\U0001F5FF"  # symbols & pictographs
        u"\U0001F680-\U0001F6FF"  # transport & map symbols
        u"\U0001F1E0-\U0001F1FF"  # flags
        u"\U00002702-\U000027B0"
        u"\U000024C2-\U0001F251"
        "]+", flags=re.UNICODE)
    
    text = emoji_pattern.sub('', text)
    
    # Убираем вводные слова и фразы
    water_words = [
        'кажется', 'возможно', 'стоит попробовать', 'наверное', 'пожалуй',
        'как известно', 'как говорится', 'не секрет что', 'все мы знаем',
        'каждый предприниматель знает', 'как вы уже догадались',
        'хочу сказать', 'хочу отметить', 'следует отметить',
        'к сожалению', 'к счастью', 'честно говоря', 'по правде говоря'
    ]
    
    text_lower = text.lower()
    for word in water_words:
        text = re.sub(r'\b' + word + r'\b[,\.]*\s*', '', text, flags=re.IGNORECASE)
    
    return text.strip()


def _rewrite_in_nata_style(text: str) -> str:
    """Переписывает в стиле Наты Анарбаевой"""
    
    # Захваты (провокации)
    hooks = [
        "Хватит писать контент в никуда.",
        "У тебя нет результата? Дело не в алгоритмах.",
        "Ты снова делаешь посты, которые никому не нужны.",
        "Разрешите себе публиковать много плохого контента.",
        "Твой контент не продаёт? Вот почему.",
        "Перестань гоняться за охватами.",
        "Ты тратишь время на контент, который не конвертит.",
        "Хватит ныть про алгоритмы.",
        "Твоя аудитория не хочет твой контент. Вот правда.",
        "Ты создаёшь контент для призраков."
    ]
    
    # Финалы (призывы к действию)
    closures = [
        "Вот тебе патрон. Применяй.",
        "Теперь перестань ныть и сделай.",
        "Целься. Стреляй. Попадёшь.",
        "Это не мотивация. Это инструкция.",
        "Время боевых действий.",
        "Бери и делай. Или закрывай лавочку.",
        "Вот тебе мой боевой патрон. Используй.",
        "Хватит стрелять холостыми.",
        "Целься в голову. Стреляй.",
        "Вот оружие. Вперёд в бой."
    ]
    
    # Боевые метафоры для замены
    metaphors = {
        'работать над': 'воевать с',
        'создавать контент': 'заряжать патроны',
        'продвигать': 'атаковать',
        'конкуренция': 'поле боя',
        'проблема': 'враг',
        'решение': 'оружие',
        'стратегия': 'боевой план',
        'цель': 'мишень',
        'результат': 'победа',
        'усилия': 'боевые действия',
        'привлечь клиентов': 'захватить территорию',
        'анализировать': 'разведка',
        'запуск': 'штурм',
        'продажи': 'трофеи'
    }
    
    import random
    
    # Выбираем случайный захват
    hook = random.choice(hooks)
    
    # Обрабатываем основной текст
    # Разбиваем на предложения
    sentences = text.replace('!', '.').replace('?', '.').split('.')
    sentences = [s.strip() for s in sentences if s.strip() and len(s.strip()) > 10]
    
    # Берём 1-3 самых ёмких предложения
    core_sentences = sentences[:3] if len(sentences) >= 3 else sentences
    
    # Переписываем с боевыми метафорами
    rewritten = []
    for sent in core_sentences:
        for old, new in metaphors.items():
            if old.lower() in sent.lower():
                sent = sent.replace(old, new).replace(old.capitalize(), new.capitalize())
        rewritten.append(sent)
    
    # Если ничего не получилось, берём суть
    if not rewritten:
        rewritten = [text[:150] + "..." if len(text) > 150 else text]
    
    # Собираем структуру
    result_parts = [hook]
    
    # Добавляем разбор (2-3 пункта)
    for i, sent in enumerate(rewritten[:3], 1):
        # Делаем предложения короче и резче
        short = _make_short_and_sharp(sent)
        if short:
            result_parts.append(f"{i}. {short}")
    
    # Добавляем финал
    closure = random.choice(closures)
    result_parts.append(closure)
    
    return '\n\n'.join(result_parts)


def _make_short_and_sharp(text: str) -> str:
    """Делает предложение коротким и резким"""
    # Убираем лишние слова
    words = text.split()
    
    # Ограничиваем длину
    if len(words) > 15:
        words = words[:15]
    
    result = ' '.join(words)
    
    # Убираем мягкие окончания
    result = result.replace('можно ', '')
    result = result.replace('нужно ', '')
    result = result.replace('стоит ', '')
    result = result.replace('следует ', '')
    result = result.replace('попробуй ', 'Делай ')
    result = result.replace('попробуйте ', 'Делайте ')
    
    # Заменяем на прямые команды
    result = result.replace('если вы ', 'ты ')
    result = result.replace('когда вы ', 'ты ')
    result = result.replace('для того чтобы ', 'чтобы ')
    
    return result.strip()


import os
import httpx
from dotenv import load_dotenv
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

NATA_SYSTEM_PROMPT = """Ты - Ната Анарбаева. Маркетинг — это бой. Я не мотивирую. Я даю патроны.

# ЗАДАЧА
Перепиши текст в моём стиле. Сохрани смысл и основную мысль. НЕ придумывай новые факты. НЕ добавляь то, чего не было.

# МОЙ СТИЛЬ
- Дерзко-экспертный, фамильярный тон
- Говоришь как старший друг-практик, не как ментор сверху
- Жёсткая прямота и уверенность
- Короткие рубленые предложения
- Структура: провокация → логика → вывод

# ЖАРГОНИЗМЫ (используй где уместно)
- пофиксить = исправить
- промты = prompts  
- нейронка = нейросеть
- кринж = неловкий, стыдный контент
- ЦА = целевая аудитория
- лидмагнит = lead magnet
- боли = боли клиента

# ХАРАКТЕРНЫЕ ФРАЗЫ
- "Вуаля" - завершение инструкций с лёгкой иронией
- "Смотри, вот почему у тебя не работает"
- "Успешный маркетолог — всегда при деньгах. Аксиома"
- "Пишет как твой бывший мудак — без эмоций"

# ПРАВИЛА
1. Сохрани ВСЮ основную мысль оригинала
2. Сохрани все факты, цифры, имена, названия инструментов
3. НЕ добавляй новые примеры или факты
4. НЕ меняй логику повествования
5. Используй 1-2 жаргонизма где уместно
6. Если в оригинале есть вопрос в конце - оставь или переформулируй
7. Можно добавить один короткий CTA в конце (1-2 предложения максимум)
8. НЕ добавляй эмодзи если их не было в оригинале

# ЗАПРЕЩЕНО
- Менять смысл поста
- Добавлять факты, которых не было
- Менять порядок аргументации
- Использовать "водяные" слова: "на самом деле", "честно говоря", "короче"
- Начинать с "Конечно", "Вот", "Готово"

# ОРИГИНАЛ:
<<<
{original_text}
>>>

Перепиши в моём стиле. Верни ТОЛЬКО готовый текст поста. Без пояснений, без преамбулы."""


def strip_markdown(text: str) -> str:
    """Убирает markdown-разметку из текста"""
    import re
    # Убираем жирный и курсив
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'_(.+?)_', r'\1', text)
    # Убираем зачеркнутый и подчеркнутый
    text = re.sub(r'~~(.+?)~~', r'\1', text)
    text = re.sub(r'\+\+(.+?)\+\+', r'\1', text)
    # Убираем код
    text = re.sub(r'`(.+?)`', r'\1', text)
    text = re.sub(r'```[\s\S]*?```', '', text)
    # Убираем ссылки [text](url) -> text
    text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)
    return text


async def adapt_content(text: str, plain_text: bool = False) -> str:
    """Адаптирует текст под стиль Наты Анарбаевой с помощью AI"""
    if len(text) < 30:
        return text
    
    prompt = NATA_SYSTEM_PROMPT.replace("{original_text}", text)
    
    result = text
    
    if GEMINI_API_KEY:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={GEMINI_API_KEY}",
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {"temperature": 0.9}
                    },
                    timeout=30
                )
                result = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            print(f"[nata_adapter] Gemini error: {e}")
    
    if result == text and OPENAI_API_KEY:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                    json={
                        "model": "gpt-4.1-mini",
                        "messages": [{"role": "system", "content": prompt}],
                        "temperature": 0.9
                    },
                    timeout=30
                )
                result = r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"[nata_adapter] OpenAI error: {e}")
    
    # Для Max убираем markdown
    if plain_text:
        result = strip_markdown(result)
    
    return result


async def adapt_content_max(text: str) -> str:
    """Адаптирует текст для Max (без markdown)"""
    return await adapt_content(text, plain_text=True)
