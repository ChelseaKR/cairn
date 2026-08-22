"""System strings, per interface language.

Everything Cairn says in its own voice lives here — the refusal, the note that
the only available source is in another language, the labels on the chat
interface. Corpus content is never translated: it is quoted verbatim in
whatever language it was written in, because a translated policy amount is an
unsourced policy amount.

Two rules this module enforces, both tested:

1. Every language carries every key. A missing key would silently serve
   English to a Spanish or Arabic speaker, which is worse than a visible gap.
   Each refusal says both halves of what a refusal has to say: there is no
   source, and I cannot help with this. The Spanish one used to say only the
   first half, which an audit of recorded answers caught — a standard refusal
   detector read it as an answer, and so would a person skimming.
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
            "I don't have a source for that, so I can't help with this question. "
            "None of the official documents this assistant is allowed to answer "
            "from cover it, and I won't guess.\n"
            "For help from a person, contact {contact}."
        ),
        "cross_language_notice": (
            "The only source I have for this is written in another language "
            "({language}). It is quoted below exactly as published."
        ),
        # The same statement when more than one passage is quoted, which
        # `retrieval.max_passages` above 1 makes possible. The singular
        # wording claims two things that are then false — that there is one
        # source, and that it is the language named — so it is not reused.
        "cross_language_notice_partial": (
            "Some of the sources below are written in another language "
            "({language}). They are quoted exactly as published."
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
            "No tengo ninguna fuente para eso, así que no puedo ayudarle con esta "
            "pregunta. Ninguno de los documentos oficiales de los que este "
            "asistente puede responder la cubre, y no voy a adivinar.\n"
            "Para recibir ayuda de una persona, comuníquese con {contact}."
        ),
        "cross_language_notice": (
            "La única fuente que tengo para esto está escrita en otro idioma "
            "({language}). Se cita a continuación tal como fue publicada."
        ),
        "cross_language_notice_partial": (
            "Algunas de las fuentes citadas abajo están escritas en otro idioma "
            "({language}). Se citan tal como fueron publicadas."
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
            "ليس لدي مصدر لهذا، ولا يمكنني مساعدتك في هذا السؤال. لا تغطيه أي من "
            "الوثائق الرسمية المسموح لهذا المساعد بالإجابة منها، ولن أخمّن.\n"
            "للحصول على مساعدة من شخص، تواصل مع {contact}."
        ),
        "cross_language_notice": (
            "المصدر الوحيد المتاح لهذا مكتوب بلغة أخرى ({language})، وهو مقتبس "
            "أدناه كما نُشر تمامًا."
        ),
        "cross_language_notice_partial": (
            "بعض المصادر أدناه مكتوبة بلغة أخرى ({language})، وهي مقتبسة كما "
            "نُشرت تمامًا."
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
    "fr": {
        "refusal": (
            "Je n'ai aucune source pour cela, donc je ne peux pas vous aider avec "
            "cette question. Aucun des documents officiels à partir desquels cet "
            "assistant est autorisé à répondre ne couvre ce sujet, et je ne vais "
            "pas deviner.\n"
            "Pour obtenir de l'aide d'une personne, contactez {contact}."
        ),
        "cross_language_notice": (
            "La seule source dont je dispose pour cela est rédigée dans une autre "
            "langue ({language}). Elle est citée ci-dessous exactement telle "
            "qu'elle a été publiée."
        ),
        "cross_language_notice_partial": (
            "Certaines des sources ci-dessous sont rédigées dans une autre langue "
            "({language}). Elles sont citées exactement telles qu'elles ont été "
            "publiées."
        ),
        "sources_heading": "Sources :",
        "page_title": "Cairn — questions sur les aides du comté de Harbor",
        "skip_link": "Aller à la zone de question",
        "heading_main": "Posez une question sur les aides du comté de Harbor",
        "disclosure_heading": "Ce qu'est cet assistant",
        "disclosure_ai": (
            "Vous parlez à un système d'intelligence artificielle, pas à une "
            "personne. Ce n'est ni un membre du personnel ni un travailleur social."
        ),
        "disclosure_sources": (
            "Il répond uniquement à partir des documents officiels indiqués avec "
            "chaque réponse. Si ces documents ne couvrent pas votre question, il "
            "le dira et vous orientera vers une personne plutôt que de deviner."
        ),
        "disclosure_limits": (
            "Il ne peut pas donner de conseil juridique, et il ne peut ni "
            "consulter ni modifier vos dossiers personnels, vos aides ou vos "
            "demandes."
        ),
        "disclosure_synthetic": (
            "Cette démonstration répond à partir de documents inventés sur un "
            "comté inventé. Rien de ce qu'elle dit ne décrit un programme d'aide "
            "réel."
        ),
        "transcript_heading": "Discussion",
        "transcript_empty": (
            "Aucune question pour l'instant. Votre conversation apparaîtra ici."
        ),
        "form_heading": "Votre question",
        "input_label": "Saisissez votre question",
        "input_hint": (
            "Appuyez sur Entrée pour envoyer. Appuyez sur Maj et Entrée ensemble "
            "pour un retour à la ligne."
        ),
        "send_button": "Envoyer la question",
        "language_label": "Langue",
        "you_said": "Vous avez demandé",
        "assistant_said": "Réponse",
        "assistant_refused": "Aucune réponse",
        "status_working": "Traitement de votre question en cours.",
        "status_answered": "Réponse prête, avec {count} source(s) indiquée(s) ci-dessous.",
        "status_refused": "Aucune source trouvée. L'assistant n'a pas répondu.",
        "error_request_failed": (
            "Une erreur s'est produite lors de l'envoi de votre question. Rien "
            "n'a été répondu. Veuillez réessayer."
        ),
        "error_empty_question": "Veuillez saisir une question avant de l'envoyer.",
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
