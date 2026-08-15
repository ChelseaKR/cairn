"""The shared probe sets, and the calibration they pin.

These are not fixtures for one test file: they are the measurement the
retrieval threshold was chosen from, so they live in one place and every suite
that cares reads them from here. If a corpus edit or a scorer change squeezes
the gap the threshold sits in, ``test_answering`` fails rather than letting the
calibration rot quietly in a comment.
"""

# (question, passage id holding the fact, the fact as it appears there)
IN_CORPUS = [
    # --- English
    (
        "How much is the monthly grocery allowance for one person?",
        "grocery-allowance-en#2",
        "$212",
    ),
    (
        "How much unpaid rent does the housing relief grant cover?",
        "housing-relief-en#2",
        "$3,500",
    ),
    (
        "When is the deadline to apply for the housing grant?",
        "housing-relief-en#4",
        "September 30",
    ),
    ("How much does the GoPass cost per year?", "transit-pass-en#2", "$20"),
    ("Who can apply for the grocery allowance?", "grocery-allowance-en#3", "$2,430"),
    ("How much is the winter utility credit worth each month?", "utility-credit-en#2", "$95"),
    # --- Spanish
    (
        "Cuanto recibe un hogar de una persona del subsidio de alimentos?",
        "grocery-allowance-es#2",
        "$212",
    ),
    ("Cuanto cubre la subvencion de alivio de vivienda?", "housing-relief-es#2", "$3,500"),
    (
        "Cual es la fecha limite para solicitar la subvencion de vivienda?",
        "housing-relief-es#4",
        "30 de septiembre",
    ),
    ("Cuanto vale el credito de servicios publicos de invierno?", "utility-credit-es#2", "$95"),
    # --- Arabic (right to left)
    (
        "كم تحصل الأسرة المكونة من شخص واحد شهريًا من مخصص البقالة؟",
        "grocery-allowance-ar#2",
        "$212",
    ),
    ("ما المبلغ الذي تغطيه منحة إغاثة السكن؟", "housing-relief-ar#2", "$3,500"),
    ("ما هو الموعد النهائي لتقديم طلب منحة السكن؟", "housing-relief-ar#4", "30 سبتمبر"),
    ("ما هي حدود الدخل لمخصص البقالة؟", "grocery-allowance-ar#3", "$2,430"),
    ("كم قيمة رصيد المرافق الشتوي شهريًا؟", "utility-credit-ar#2", "$95"),
]

# Plausible things a person walks up and asks a county assistant, none of them
# covered by the corpus. Each language gets its own, because a false accept is
# a per-language failure: the scorer's statistics are per-language too.
OFF_TOPIC = [
    "Can you help me renew my drivers license?",
    "What is the capital of France?",
    "How do I file my federal income taxes?",
    "Is the library open on Sunday?",
    "What vaccinations does my dog need?",
    "Do you offer job training classes?",
    "Where do I register to vote?",
    "How do I get a building permit?",
    "Puede ayudarme a renovar mi licencia de conducir?",
    "Cual es la capital de Francia?",
    "Que vacunas necesita mi perro?",
    "Ofrecen clases de capacitacion laboral?",
    "Donde me registro para votar?",
    "Como obtengo un permiso de construccion?",
    "هل يمكنك مساعدتي في تجديد رخصة القيادة؟",
    "ما هي عاصمة فرنسا؟",
    "متى تفتح المكتبة يوم الأحد؟",
    "ما اللقاحات التي يحتاجها كلبي؟",
    "كيف أقدم إقراري الضريبي الفيدرالي؟",
    "أين أسجل للتصويت؟",
]

# Measured 2026-08-15 against the three-language demo corpus (see DESIGN.md).
# The configured threshold must sit strictly between these, with room on both
# sides — a threshold pressed against either edge is a threshold that will
# start refusing real questions the first time a document is edited.
MEASURED_WORST_IN_CORPUS = 0.196
MEASURED_BEST_OFF_TOPIC = 0.122
