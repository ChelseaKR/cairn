"""System strings, per interface language.

Everything Cairn says in its own voice lives here — the refusal, the note that
the only available source is in another language, the labels on the chat
interface. Corpus content is never translated: it is quoted verbatim in
whatever language it was written in, because a translated policy amount is an
unsourced policy amount.

Two rules this module enforces, both tested:

1. Every language carries every key. A missing key would silently serve
   English to a Spanish or Arabic speaker, which is worse than a visible gap.
2. A key's placeholders are the same in every language. ``{contact}``,
   ``{language}``, and ``{count}`` are the whole vocabulary; anything else is
   a typo waiting to raise at the worst possible moment.
"""

from __future__ import annotations

# Reference language: the set of keys every other language must match, and the
# fallback for a code with no catalogue of its own.
DEFAULT_LANG = "en"

CATALOGUE: dict[str, dict[str, str]] = {
    "en": {
        # --- engine voice ---
        "refusal": (
            "I don't have a source for that. None of the official documents this "
            "assistant is allowed to answer from cover your question, and I won't "
            "guess.\nFor help from a person, contact {contact}."
        ),
        "cross_language_notice": (
            "The only source I have for this is written in another language "
            "({language}). It is quoted below exactly as published."
        ),
        "sources_heading": "Sources:",
        # --- chat interface ---
        "page_title": "Cairn — ask about Harbor County benefits",
        "skip_link": "Skip to the question box",
        "heading_main": "Ask about Harbor County benefits",
        "disclosure_heading": "What this assistant is",
        "disclosure_ai": (
            "You are talking to an AI system, not a person. It is not staff and "
            "not a caseworker."
        ),
        "disclosure_sources": (
            "It answers only from the official documents listed with each answer. "
            "If those documents do not cover your question, it will say so and "
            "point you to a person instead of guessing."
        ),
        "disclosure_limits": (
            "It cannot give legal advice, and it cannot see or change your "
            "personal records, benefits, or applications."
        ),
        "disclosure_synthetic": (
            "This demonstration answers from invented documents about an invented "
            "county. Nothing it says describes a real benefit program."
        ),
        "transcript_heading": "Conversation",
        "transcript_empty": "No questions yet. Your conversation will appear here.",
        "form_heading": "Your question",
        "input_label": "Type your question",
        "input_hint": "Press Enter to send. Press Shift and Enter together for a new line.",
        "send_button": "Send question",
        "language_label": "Language",
        "you_said": "You asked",
        "assistant_said": "Answer",
        "assistant_refused": "No answer",
        "status_working": "Working on your question.",
        "status_answered": "Answer ready, with {count} source(s) listed below it.",
        "status_refused": "No source found. The assistant did not answer.",
        "error_request_failed": (
            "Something went wrong sending your question. Nothing was answered. "
            "Please try again."
        ),
        "error_empty_question": "Please type a question before sending.",
    },
    "es": {
        "refusal": (
            "No tengo ninguna fuente para eso. Ninguno de los documentos oficiales "
            "de los que este asistente puede responder cubre su pregunta, y no voy "
            "a adivinar.\nPara recibir ayuda de una persona, comuníquese con {contact}."
        ),
        "cross_language_notice": (
            "La única fuente que tengo para esto está escrita en otro idioma "
            "({language}). Se cita a continuación tal como fue publicada."
        ),
        "sources_heading": "Fuentes:",
        "page_title": "Cairn — preguntas sobre los beneficios del Condado de Harbor",
        "skip_link": "Ir al cuadro de preguntas",
        "heading_main": "Pregunte sobre los beneficios del Condado de Harbor",
        "disclosure_heading": "Qué es este asistente",
        "disclosure_ai": (
            "Está hablando con un sistema de inteligencia artificial, no con una "
            "persona. No es personal del condado ni un trabajador social."
        ),
        "disclosure_sources": (
            "Responde únicamente a partir de los documentos oficiales que aparecen "
            "con cada respuesta. Si esos documentos no cubren su pregunta, lo dirá "
            "y le indicará a quién acudir en lugar de adivinar."
        ),
        "disclosure_limits": (
            "No puede dar asesoramiento legal, y no puede ver ni cambiar sus "
            "registros personales, sus beneficios ni sus solicitudes."
        ),
        "disclosure_synthetic": (
            "Esta demostración responde a partir de documentos inventados sobre un "
            "condado inventado. Nada de lo que dice describe un programa real."
        ),
        "transcript_heading": "Conversación",
        "transcript_empty": "Aún no hay preguntas. Su conversación aparecerá aquí.",
        "form_heading": "Su pregunta",
        "input_label": "Escriba su pregunta",
        "input_hint": (
            "Pulse Intro para enviar. Pulse Mayúsculas e Intro juntas para una línea nueva."
        ),
        "send_button": "Enviar pregunta",
        "language_label": "Idioma",
        "you_said": "Usted preguntó",
        "assistant_said": "Respuesta",
        "assistant_refused": "Sin respuesta",
        "status_working": "Procesando su pregunta.",
        "status_answered": "Respuesta lista, con {count} fuente(s) indicada(s) debajo.",
        "status_refused": "No se encontró ninguna fuente. El asistente no respondió.",
        "error_request_failed": (
            "Algo salió mal al enviar su pregunta. No se respondió nada. "
            "Inténtelo de nuevo."
        ),
        "error_empty_question": "Escriba una pregunta antes de enviarla.",
    },
    "ar": {
        "refusal": (
            "ليس لدي مصدر لهذا. لا تغطي سؤالك أي من الوثائق الرسمية المسموح لهذا "
            "المساعد بالإجابة منها، ولن أخمّن.\n"
            "للحصول على مساعدة من شخص، تواصل مع {contact}."
        ),
        "cross_language_notice": (
            "المصدر الوحيد المتاح لهذا مكتوب بلغة أخرى ({language})، وهو مقتبس "
            "أدناه كما نُشر تمامًا."
        ),
        "sources_heading": "المصادر:",
        "page_title": "كايرن — اسأل عن مساعدات مقاطعة هاربر",
        "skip_link": "انتقل إلى مربع السؤال",
        "heading_main": "اسأل عن مساعدات مقاطعة هاربر",
        "disclosure_heading": "ما هذا المساعد",
        "disclosure_ai": (
            "أنت تتحدث إلى نظام ذكاء اصطناعي، لا إلى شخص. وهو ليس موظفًا ولا "
            "أخصائي حالات."
        ),
        "disclosure_sources": (
            "يجيب فقط اعتمادًا على الوثائق الرسمية المذكورة مع كل إجابة. وإذا لم "
            "تغطِّ تلك الوثائق سؤالك، فسيقول ذلك ويرشدك إلى شخص بدلًا من التخمين."
        ),
        "disclosure_limits": (
            "لا يمكنه تقديم استشارة قانونية، ولا يمكنه الاطلاع على سجلاتك الشخصية "
            "أو مساعداتك أو طلباتك ولا تغييرها."
        ),
        "disclosure_synthetic": (
            "هذا العرض التوضيحي يجيب من وثائق مُختلَقة عن مقاطعة مُختلَقة. ولا شيء "
            "مما يقوله يصف برنامج مساعدات حقيقيًا."
        ),
        "transcript_heading": "المحادثة",
        "transcript_empty": "لا توجد أسئلة بعد. ستظهر محادثتك هنا.",
        "form_heading": "سؤالك",
        "input_label": "اكتب سؤالك",
        "input_hint": "اضغط Enter للإرسال. اضغط Shift مع Enter معًا لسطر جديد.",
        "send_button": "إرسال السؤال",
        "language_label": "اللغة",
        "you_said": "سألتَ",
        "assistant_said": "الإجابة",
        "assistant_refused": "لا توجد إجابة",
        "status_working": "جارٍ معالجة سؤالك.",
        "status_answered": "الإجابة جاهزة، ومعها {count} مصدر/مصادر مذكورة أسفلها.",
        "status_refused": "لم يُعثر على أي مصدر. لم يجب المساعد.",
        "error_request_failed": (
            "حدث خطأ أثناء إرسال سؤالك. لم تتم الإجابة على شيء. يرجى المحاولة مرة أخرى."
        ),
        "error_empty_question": "اكتب سؤالًا قبل الإرسال.",
    },
}


def catalogue_for(lang: str) -> dict[str, str]:
    """The strings for ``lang``, falling back to the reference language for a
    code with no catalogue (a corpus language is not necessarily an interface
    language)."""
    return CATALOGUE.get(lang, CATALOGUE[DEFAULT_LANG])


def text(key: str, lang: str, **fields: object) -> str:
    """One system string, formatted. Raises on an unknown key rather than
    serving an empty box to a user."""
    catalogue = catalogue_for(lang)
    if key not in catalogue:
        raise KeyError(f"no message {key!r} in the {lang!r} catalogue")
    return catalogue[key].format(**fields) if fields else catalogue[key]
