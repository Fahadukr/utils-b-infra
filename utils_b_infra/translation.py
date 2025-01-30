from typing import Literal

from utils_b_infra.generic import retry_with_timeout


class TextTranslator:
    """
    To use google translate, set GOOGLE_APPLICATION_CREDENTIALS env variable
    to the path of the google service account json file before using this class:
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = join(current_path, 'google_service_account.json')

    Requires:
        the utils-b-infra package with the translation extras:
        pip install utils-b-infra[translation]

    Parameters:
        deepl_api_key (str): API key for DeepL.
        languages (dict[str, str]): Supported language mappings.
        google_project_id (str): Google Cloud project ID.
    """

    def __init__(self, languages: dict[str, str], deepl_api_key: str = None, google_project_id: str = None):
        if not deepl_api_key and not google_project_id:
            raise ValueError("Either 'deepl_api_key' or 'google_project_id' must be provided.")

        self.languages = languages
        self.deepl_translate_client = None
        self.google_translate_client = None

        if deepl_api_key:
            import deepl
            self.deepl_translate_client = deepl.Translator(deepl_api_key)

        if google_project_id:
            try:
                from google.cloud.translate_v3 import TranslationServiceClient as GoogleTranslationServiceClient
                from google.cloud.translate_v3.types import TranslateTextRequest
            except ImportError:
                raise ImportError(
                    "Please install the translation dependencies with: pip install utils-b-infra[translation]")
            self.TranslateTextRequest = TranslateTextRequest
            self.google_translate_client = GoogleTranslationServiceClient()
            self.google_project_id = google_project_id

    @retry_with_timeout(retries=3, timeout=120, initial_delay=20, backoff=2)
    def _translate_text_with_google(self,
                                    text_to_translate: str,
                                    source_language: str,
                                    target_lang: str,
                                    mime_type: str) -> str:
        """Translates text into the target language.

        Target must be an ISO 639-1 language code.
        See https://cloud.google.com/translate/docs/languages for the supported languages
        """

        # Prepare the request
        request = self.TranslateTextRequest(
            parent=f"projects/{self.google_project_id}",
            contents=[text_to_translate],
            mime_type=mime_type,  # mime types: text/plain, text/html
            source_language_code=source_language,
            target_language_code=target_lang,
        )

        # Perform the translation
        response = self.google_translate_client.translate_text(request=request)

        # Extract the translated text
        translated_text = response.translations[0].translated_text

        return translated_text

    @retry_with_timeout(retries=2, timeout=120, initial_delay=30, backoff=2)
    def _translate_text_with_deepl(self,
                                   text_to_translate: str,
                                   source_lang: str,
                                   target_lang: str,
                                   tag_handling: str = None):
        result = self.deepl_translate_client.translate_text(
            text=text_to_translate,
            source_lang=source_lang.upper(),
            target_lang=target_lang,
            tag_handling=tag_handling
        )
        # The result is a list of TextResult objects, or a single TextResult object if the text was one string.
        if isinstance(result, list):
            return result[0].text
        return result.text

    def get_translations(self,
                         text: str,
                         replace_lang_url: bool = False,
                         source_language: Literal["en", "ru", "ar", "de", "es", "fr", "uk", "pl"] = "en",
                         target_langs: list[Literal["en", "ru", "ar", "de", "es", "fr", "uk", "pl"]] = None,
                         engine: Literal["google", "deepl"] = "google",
                         google_mime_type: Literal["text/plain", "text/html"] = "text/plain",
                         deepl_tag_handling: str = None) -> dict[str, str]:
        """
        Translate text to all languages in LANGUAGES dict
        :param text: text to translate
        :param replace_lang_url: replace base url with the base url from target language in the text.
        :param source_language: source language ['en', 'ru', 'ar', 'de', 'es', 'fr', 'uk', 'pl']
        :param target_langs: list of languages to translate to, if None, translate to all languages in LANGUAGES dict
        :param engine: the translation engine to use, either "google" or "deepl"
        :param google_mime_type: for Google only, mime type of the text, either "text/plain" or "text/html"
        :param deepl_tag_handling: for deepl only, how to handle tags in the text, either "xml" or "html"
        :return: dict with translations
        """
        if engine and engine not in ["google", "deepl"]:
            raise ValueError("engine must be either 'google' or 'deepl'")
        if source_language not in ['en', 'ru', 'ar', 'de', 'es', 'fr', 'uk', 'pl']:
            raise ValueError("source_language must be one of 'en', 'ru', 'ar', 'de', 'es', 'fr', 'uk', 'pl'")
        if target_langs and not all(lang in self.languages for lang in target_langs):
            raise ValueError("target_langs must be a list of 'en', 'ru', 'ar', 'de', 'es', 'fr', 'uk', 'pl'")

        translations = {source_language: text}
        if not text:
            return translations

        for lang in self.languages:
            if lang == source_language:
                continue

            if target_langs and lang not in target_langs:
                continue

            if engine == "google":
                translated_text = self._translate_text_with_google(
                    text_to_translate=text,
                    source_language=source_language,
                    target_lang=lang,
                    mime_type=google_mime_type
                )
            elif engine == "deepl":
                translated_text = self._translate_text_with_deepl(
                    text_to_translate=text,
                    source_lang=source_language,
                    target_lang=lang,
                    tag_handling=deepl_tag_handling
                )
            else:
                raise ValueError("engine must be either 'google' or 'deepl'")

            if replace_lang_url:
                translated_text = translated_text.replace('https://us-uk.bookimed.com/',
                                                          self.languages[lang])

            if lang == 'uk':
                lang = 'ua'

            translations[lang] = translated_text

        return translations
