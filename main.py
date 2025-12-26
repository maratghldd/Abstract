import os
from pathlib import Path
from transformers import T5ForConditionalGeneration, T5Tokenizer
import torch

# ============= ИЗВЛЕЧЕНИЕ ТЕКСТА ИЗ ФАЙЛОВ =============

try:
    import pdfplumber

    PDF_SUPPORT = True
except ImportError:
    print("⚠️  pdfplumber не установлен. Для работы с PDF установите: pip install pdfplumber")
    PDF_SUPPORT = False

try:
    from docx import Document

    DOCX_SUPPORT = True
except ImportError:
    print("⚠️  python-docx не установлен. Для работы с DOCX установите: pip install python-docx")
    DOCX_SUPPORT = False


def extract_text_from_file(file_path):
    """
    Извлекает текст из файлов PDF, DOCX, DOC, TXT

    Args:
        file_path: Путь к файлу

    Returns:
        Текст из файла или None в случае ошибки
    """
    try:
        file_extension = Path(file_path).suffix.lower()

        if file_extension == '.pdf' and PDF_SUPPORT:
            return extract_text_from_pdf(file_path)
        elif file_extension == '.docx' and DOCX_SUPPORT:
            return extract_text_from_docx(file_path)
        elif file_extension == '.txt':
            return extract_text_from_txt(file_path)
        else:
            print(f"❌ Неподдерживаемый формат или отсутствует библиотека: {file_extension}")
            return None

    except Exception as e:
        print(f"❌ Ошибка при чтении файла {file_path}: {str(e)[:100]}")
        return None


def extract_text_from_pdf(pdf_path):
    """Извлекает текст из PDF файла"""
    try:
        text_parts = []

        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)

        full_text = '\n\n'.join(text_parts)
        if full_text:
            print(f"📄 PDF: прочитано {len(pdf.pages)} страниц, {len(full_text)} символов")
        else:
            print(f"⚠️  PDF: не удалось извлечь текст (возможно, сканированный документ)")
        return full_text

    except Exception as e:
        print(f"❌ Ошибка при чтении PDF: {str(e)[:100]}")
        return None


def extract_text_from_docx(docx_path):
    """Извлекает текст из DOCX файла"""
    try:
        doc = Document(docx_path)
        text_parts = []

        for paragraph in doc.paragraphs:
            if paragraph.text.strip():
                text_parts.append(paragraph.text)

        full_text = '\n\n'.join(text_parts)
        print(f"📄 DOCX: прочитано {len(full_text)} символов")
        return full_text

    except Exception as e:
        print(f"❌ Ошибка при чтении DOCX: {str(e)[:100]}")
        return None


def extract_text_from_txt(txt_path):
    """Читает текст из TXT файла"""
    try:
        # Пробуем разные кодировки для русского текста
        encodings = ['utf-8', 'cp1251', 'koi8-r']

        for encoding in encodings:
            try:
                with open(txt_path, 'r', encoding=encoding) as f:
                    text = f.read()
                print(f"📄 TXT: прочитано {len(text)} символов (кодировка: {encoding})")
                return text
            except UnicodeDecodeError:
                continue

        # Если не сработало, читаем с игнорированием ошибок
        with open(txt_path, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()
        print(f"📄 TXT: прочитано {len(text)} символов (с игнорированием ошибок)")
        return text

    except Exception as e:
        print(f"❌ Ошибка при чтении TXT: {str(e)[:100]}")
        return None


# ============= ГЕНЕРАЦИЯ АННОТАЦИИ ДО 35 СЛОВ =============

def generate_annotation(text, max_words=35, model_path="./models/rut5_base_sum_gazeta"):
    """
    Генерирует аннотацию (название) для текста до указанного количества слов

    Args:
        text: Входной текст
        max_words: Максимальное количество слов в аннотации (по умолчанию 35)
        model_path: Путь к модели

    Returns:
        Сгенерированная аннотация
    """
    if not text or len(text.strip()) == 0:
        return "Текст не найден"

    try:
        # Загружаем модель
        tokenizer = T5Tokenizer.from_pretrained(model_path, local_files_only=True)
        model = T5ForConditionalGeneration.from_pretrained(model_path, local_files_only=True)
        model.to('cpu')

        # Автонастройка параметров в зависимости от max_words
        if max_words <= 15:
            max_length = 40
            length_penalty = 1.2
        elif max_words <= 25:
            max_length = 55
            length_penalty = 1.0
        elif max_words <= 35:
            max_length = 70
            length_penalty = 0.9
        else:  # >35
            max_length = 85
            length_penalty = 0.8

        # Определяем размер контекста
        context_length = min(500 + (max_words * 10), 1000)
        context = text[:context_length]

        # Подготавливаем промпт
        prompt = f"Заголовок документа: {context}"
        inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=512)

        # Генерируем аннотацию
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_length=max_length,
                min_length=max(15, int(max_words * 0.3)),  # Минимум 30% от max_words
                num_beams=3,
                early_stopping=True,
                repetition_penalty=1.2,
                length_penalty=length_penalty,
                no_repeat_ngram_size=2
            )

        # Получаем и очищаем результат
        title = tokenizer.decode(outputs[0], skip_special_tokens=True)
        title = title.replace("Заголовок документа:", "").replace("Заголовок:", "").strip()

        # Берем до первого предложения, если оно не слишком короткое
        sentences = title.split('.')
        if len(sentences) > 1:
            first = sentences[0].strip()
            if len(first.split()) >= 5:
                title = first
            elif len('. '.join(sentences[:2]).strip().split()) <= max_words:
                title = '. '.join(sentences[:2]).strip()

        # Убираем лишние точки
        title = title.rstrip('. ')

        # Обрезаем до max_words
        words = title.split()
        if len(words) > max_words:
            title = " ".join(words[:max_words])

        return title.strip()

    except Exception as e:
        print(f"❌ Ошибка при генерации аннотации: {str(e)[:100]}")
        return "Ошибка генерации"


# ============= ОСНОВНАЯ ФУНКЦИЯ ДЛЯ РАБОТЫ С ФАЙЛАМИ =============

def generate_annotation_from_file(file_path, max_words=35):
    """
    Полный пайплайн: файл → текст → аннотация

    Args:
        file_path: Путь к файлу (PDF, DOCX, TXT)
        max_words: Максимальное количество слов в аннотации

    Returns:
        Сгенерированная аннотация или сообщение об ошибке
    """
    print(f"\n{'=' * 60}")
    print(f"📁 Обработка файла: {Path(file_path).name}")
    print(f"{'=' * 60}")

    # 1. Проверяем существование файла
    if not os.path.exists(file_path):
        return f"❌ Файл не найден: {file_path}"

    # 2. Извлекаем текст
    text = extract_text_from_file(file_path)
    if not text:
        return "❌ Не удалось извлечь текст из файла"

    # 3. Генерируем аннотацию
    print("🤖 Генерирую аннотацию...")
    annotation = generate_annotation(text, max_words=max_words)

    return annotation


# ============= ПРИМЕР ИСПОЛЬЗОВАНИЯ =============

if __name__ == "__main__":
    import sys

    print("🎯 СИСТЕМА ГЕНЕРАЦИИ АННОТАЦИЙ ДЛЯ ДОКУМЕНТОВ")
    print("=" * 60)

    # Проверяем наличие необходимых библиотек
    if not PDF_SUPPORT:
        print("Для работы с PDF файлами установите: pip install pdfplumber")
    if not DOCX_SUPPORT:
        print("Для работы с DOCX файлами установите: pip install python-docx")

    # Проверяем аргументы командной строки
    if len(sys.argv) > 1:
        # Режим командной строки: python script.py путь_к_файлу [макс_слов]
        file_path = sys.argv[1]
        max_words = 35
        if len(sys.argv) > 2:
            try:
                max_words = int(sys.argv[2])
            except ValueError:
                print(f"⚠️  Некорректное число слов, использую {max_words}")

        result = generate_annotation_from_file(file_path, max_words)
        print(f"\n🏷️  Аннотация ({len(result.split())} слов):")
        print(f"   {result}")

    else:
        # Интерактивный режим
        print("\nВыберите режим:")
        print("1. Обработать один файл")
        print("2. Выход")

        choice = input("\nВведите номер (1-2): ").strip()

        if choice == "1":
            file_path = input("Введите путь к файлу (PDF, DOCX, TXT): ").strip()

            if not os.path.exists(file_path):
                print(f"❌ Файл не найден: {file_path}")
            else:
                # Запрашиваем максимальное количество слов
                max_words_input = input("Максимальное количество слов [35]: ").strip()
                max_words = 35
                if max_words_input:
                    try:
                        max_words = int(max_words_input)
                        if max_words < 5:
                            print("⚠️  Минимум 5 слов, использую 5")
                            max_words = 5
                        elif max_words > 50:
                            print("⚠️  Максимум 50 слов, использую 50")
                            max_words = 50
                    except ValueError:
                        print(f"⚠️  Некорректное число, использую {max_words}")

                result = generate_annotation_from_file(file_path, max_words)
                print(f"\n🏷️  Аннотация ({len(result.split())} слов):")
                print(f"   {result}")

                # Сохраняем результат в файл
                save_option = input("\nСохранить результат в файл? (y/n): ").strip().lower()
                if save_option == 'y':
                    output_file = f"{Path(file_path).stem}_аннотация.txt"
                    with open(output_file, 'w', encoding='utf-8') as f:
                        f.write(f"Файл: {Path(file_path).name}\n")
                        f.write(f"Аннотация ({len(result.split())} слов):\n")
                        f.write("=" * 50 + "\n")
                        f.write(result + "\n")
                    print(f"💾 Результат сохранён в: {output_file}")
        else:
            print("Выход")