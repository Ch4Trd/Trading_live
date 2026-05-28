"""
learn_command.py
/learn — Enseigne l'analyse fondamentale aux débutants, une leçon à la fois.
Suit la progression de chaque utilisateur dans SQLite.
"""

import sqlite3
import logging
from datetime import datetime
from html import escape as _esc
from pathlib import Path

from subscription import subscription_manager

log = logging.getLogger(__name__)
DB_PATH = Path(__file__).parent / "learn_progress.db"

# ── Database ───────────────────────────────────────────────────────────────────

def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_learn_progress (
            user_id    INTEGER NOT NULL,
            lesson_id  INTEGER NOT NULL,
            learned_at TEXT    DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, lesson_id)
        )
    """)
    conn.commit()
    return conn


def _get_done(user_id: int) -> set[int]:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT lesson_id FROM user_learn_progress WHERE user_id=?", (user_id,)
        ).fetchall()
    return {r[0] for r in rows}


def _mark_done(user_id: int, lesson_id: int):
    with _get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO user_learn_progress (user_id, lesson_id) VALUES (?,?)",
            (user_id, lesson_id),
        )
        conn.commit()


def _reset_progress(user_id: int):
    with _get_conn() as conn:
        conn.execute("DELETE FROM user_learn_progress WHERE user_id=?", (user_id,))
        conn.commit()


# ── Lessons ────────────────────────────────────────────────────────────────────
# Each lesson: id, emoji, topic, content per lang (fr/en/es/ar)

LESSONS: list[dict] = [
    {
        "id": 1,
        "emoji": "🌍",
        "topic": {
            "fr": "C'est quoi l'analyse fondamentale ?",
            "en": "What is fundamental analysis?",
            "es": "¿Qué es el análisis fundamental?",
            "ar": "ما هو التحليل الأساسي؟",
        },
        "content": {
            "fr": (
                "Imagine que tu veux acheter une voiture d'occasion.\n"
                "Tu ne regardes pas juste la couleur — tu veux savoir si le moteur est bon, "
                "si elle a eu des accidents, combien elle consomme.\n\n"
                "<b>C'est exactement ça, l'analyse fondamentale.</b>\n\n"
                "Au lieu d'une voiture, tu analyses un pays ou une entreprise :\n"
                "• Est-ce que l'économie va bien ? 📈\n"
                "• Est-ce que les prix augmentent trop ? 💸\n"
                "• Est-ce que les gens travaillent ? 👷\n\n"
                "Ces informations font monter ou descendre les devises et les marchés.\n\n"
                "💡 <b>Exemple :</b> Si l'économie américaine est très forte → le dollar monte.\n"
                "Si elle ralentit → le dollar baisse."
            ),
            "en": (
                "Imagine you want to buy a used car.\n"
                "You don't just look at the color — you want to know if the engine is good, "
                "if it had accidents, and how much fuel it uses.\n\n"
                "<b>That's exactly what fundamental analysis is.</b>\n\n"
                "Instead of a car, you analyze a country or a company:\n"
                "• Is the economy doing well? 📈\n"
                "• Are prices rising too fast? 💸\n"
                "• Are people employed? 👷\n\n"
                "This information makes currencies and markets go up or down.\n\n"
                "💡 <b>Example:</b> If the US economy is very strong → the dollar rises.\n"
                "If it slows down → the dollar falls."
            ),
            "es": (
                "Imagina que quieres comprar un coche de segunda mano.\n"
                "No solo miras el color — quieres saber si el motor está bien, "
                "si tuvo accidentes y cuánto consume.\n\n"
                "<b>Eso es exactamente el análisis fundamental.</b>\n\n"
                "En lugar de un coche, analizas un país o una empresa:\n"
                "• ¿La economía va bien? 📈\n"
                "• ¿Los precios suben demasiado? 💸\n"
                "• ¿La gente tiene trabajo? 👷\n\n"
                "Esta información hace subir o bajar las divisas y los mercados.\n\n"
                "💡 <b>Ejemplo:</b> Si la economía de EE.UU. es muy fuerte → el dólar sube.\n"
                "Si se ralentiza → el dólar baja."
            ),
            "ar": (
                "تخيل أنك تريد شراء سيارة مستعملة.\n"
                "لن تنظر فقط إلى اللون — بل ستريد معرفة هل المحرك جيد، "
                "هل تعرضت لحوادث، وكم تستهلك من وقود.\n\n"
                "<b>هذا بالضبط ما هو التحليل الأساسي.</b>\n\n"
                "بدلاً من سيارة، تحلل دولة أو شركة:\n"
                "• هل الاقتصاد بخير؟ 📈\n"
                "• هل الأسعار ترتفع بسرعة؟ 💸\n"
                "• هل الناس يعملون؟ 👷\n\n"
                "هذه المعلومات تجعل العملات والأسواق ترتفع أو تنخفض.\n\n"
                "💡 <b>مثال:</b> إذا كان الاقتصاد الأمريكي قوياً جداً → الدولار يرتفع.\n"
                "إذا تباطأ → الدولار ينخفض."
            ),
        },
    },
    {
        "id": 2,
        "emoji": "🏭",
        "topic": {
            "fr": "Le PIB — Le carnet de santé de l'économie",
            "en": "GDP — The economy's health report",
            "es": "El PIB — El informe de salud de la economía",
            "ar": "الناتج المحلي الإجمالي — تقرير صحة الاقتصاد",
        },
        "content": {
            "fr": (
                "<b>PIB = Produit Intérieur Brut (GDP en anglais)</b>\n\n"
                "C'est comme le bulletin de notes de tout un pays.\n"
                "Il mesure tout ce que le pays a produit et vendu en un trimestre.\n\n"
                "🟢 <b>PIB en hausse</b> → l'économie grandit → la devise monte\n"
                "🔴 <b>PIB en baisse</b> → l'économie rétrécit → la devise baisse\n"
                "⚠️ <b>2 trimestres négatifs = récession</b> — mot qui fait peur aux marchés !\n\n"
                "💡 <b>Exemple :</b>\n"
                "PIB US sort à +3.5% (attendu +2%) → surprise positive → USD monte fort, "
                "NAS100 monte, GOLD peut baisser car moins besoin de refuge."
            ),
            "en": (
                "<b>GDP = Gross Domestic Product</b>\n\n"
                "Think of it as the report card of an entire country.\n"
                "It measures everything the country produced and sold in a quarter.\n\n"
                "🟢 <b>GDP rising</b> → economy growing → currency goes up\n"
                "🔴 <b>GDP falling</b> → economy shrinking → currency goes down\n"
                "⚠️ <b>2 negative quarters = recession</b> — a word that scares markets!\n\n"
                "💡 <b>Example:</b>\n"
                "US GDP comes in at +3.5% (expected +2%) → positive surprise → USD rises, "
                "NAS100 rises, GOLD may fall as there's less need for a safe haven."
            ),
            "es": (
                "<b>PIB = Producto Interior Bruto (GDP en inglés)</b>\n\n"
                "Piénsalo como el boletín de calificaciones de todo un país.\n"
                "Mide todo lo que el país produjo y vendió en un trimestre.\n\n"
                "🟢 <b>PIB en alza</b> → economía creciendo → la divisa sube\n"
                "🔴 <b>PIB en caída</b> → economía encogiendo → la divisa baja\n"
                "⚠️ <b>2 trimestres negativos = recesión</b> — ¡palabra que asusta a los mercados!\n\n"
                "💡 <b>Ejemplo:</b>\n"
                "PIB de EE.UU. sale en +3.5% (esperado +2%) → sorpresa positiva → USD sube, "
                "NAS100 sube, GOLD puede bajar porque hay menos necesidad de refugio."
            ),
            "ar": (
                "<b>الناتج المحلي الإجمالي (GDP)</b>\n\n"
                "فكر فيه كبطاقة تقارير دولة بأكملها.\n"
                "يقيس كل ما أنتجته الدولة وباعته في ربع سنوي.\n\n"
                "🟢 <b>GDP في ارتفاع</b> → الاقتصاد ينمو → العملة ترتفع\n"
                "🔴 <b>GDP في انخفاض</b> → الاقتصاد يتقلص → العملة تنخفض\n"
                "⚠️ <b>ربعان سلبيان = ركود</b> — كلمة تخيف الأسواق!\n\n"
                "💡 <b>مثال:</b>\n"
                "GDP الأمريكي يصدر بـ +3.5% (المتوقع +2%) → مفاجأة إيجابية → الدولار يرتفع، "
                "NAS100 يرتفع، والذهب قد ينخفض لأن الحاجة للملاذ الآمن تقل."
            ),
        },
    },
    {
        "id": 3,
        "emoji": "💸",
        "topic": {
            "fr": "Le CPI — L'inflation, quand tout devient plus cher",
            "en": "CPI — Inflation, when everything gets more expensive",
            "es": "El IPC — La inflación, cuando todo se encarece",
            "ar": "مؤشر أسعار المستهلك — التضخم عندما يصبح كل شيء أغلى",
        },
        "content": {
            "fr": (
                "<b>CPI = Consumer Price Index (Indice des Prix à la Consommation)</b>\n\n"
                "Imagine que ton panier de courses coûtait 100€ l'an dernier.\n"
                "Cette année il coûte 104€ → l'inflation est de 4%.\n\n"
                "🏦 La banque centrale (la Fed aux USA) a pour mission de garder\n"
                "l'inflation autour de <b>2%</b> — pas trop chaud, pas trop froid.\n\n"
                "🔴 <b>CPI > 2%</b> → inflation élevée → la Fed monte les taux → USD monte\n"
                "🟢 <b>CPI < 2%</b> → inflation basse → la Fed peut baisser les taux → USD baisse\n\n"
                "💡 <b>Exemple :</b>\n"
                "CPI sort à 4.5% (attendu 4%) → surprise → la Fed va durcir → EUR/USD baisse."
            ),
            "en": (
                "<b>CPI = Consumer Price Index</b>\n\n"
                "Imagine your grocery basket cost $100 last year.\n"
                "This year it costs $104 → inflation is 4%.\n\n"
                "🏦 The central bank (the Fed in the US) aims to keep\n"
                "inflation around <b>2%</b> — not too hot, not too cold.\n\n"
                "🔴 <b>CPI > 2%</b> → high inflation → Fed raises rates → USD rises\n"
                "🟢 <b>CPI < 2%</b> → low inflation → Fed can cut rates → USD falls\n\n"
                "💡 <b>Example:</b>\n"
                "CPI comes in at 4.5% (expected 4%) → surprise → Fed will tighten → EUR/USD falls."
            ),
            "es": (
                "<b>IPC = Índice de Precios al Consumidor (CPI en inglés)</b>\n\n"
                "Imagina que tu cesta de la compra costaba 100€ el año pasado.\n"
                "Este año cuesta 104€ → la inflación es del 4%.\n\n"
                "🏦 El banco central (la Fed en EE.UU.) tiene como misión mantener\n"
                "la inflación alrededor del <b>2%</b> — ni muy caliente ni muy fría.\n\n"
                "🔴 <b>IPC > 2%</b> → alta inflación → la Fed sube tipos → USD sube\n"
                "🟢 <b>IPC < 2%</b> → baja inflación → la Fed puede bajar tipos → USD baja\n\n"
                "💡 <b>Ejemplo:</b>\n"
                "IPC sale en 4.5% (esperado 4%) → sorpresa → la Fed endurecerá → EUR/USD baja."
            ),
            "ar": (
                "<b>مؤشر أسعار المستهلك (CPI)</b>\n\n"
                "تخيل أن سلة مشترياتك كانت تكلف 100 دولار العام الماضي.\n"
                "هذا العام تكلف 104 دولارات → التضخم هو 4%.\n\n"
                "🏦 البنك المركزي (الفيدرالي في الولايات المتحدة) يهدف للحفاظ على\n"
                "التضخم حول <b>2%</b> — لا حار جداً ولا بارد جداً.\n\n"
                "🔴 <b>CPI > 2%</b> → تضخم مرتفع → الفيد يرفع الفائدة → الدولار يرتفع\n"
                "🟢 <b>CPI < 2%</b> → تضخم منخفض → الفيد قد يخفض الفائدة → الدولار ينخفض\n\n"
                "💡 <b>مثال:</b>\n"
                "CPI يصدر بـ 4.5% (المتوقع 4%) → مفاجأة → الفيد سيشدد → EUR/USD ينخفض."
            ),
        },
    },
    {
        "id": 4,
        "emoji": "👷",
        "topic": {
            "fr": "Le NFP — Le rapport sur l'emploi américain",
            "en": "NFP — The US jobs report",
            "es": "El NFP — El informe de empleo de EE.UU.",
            "ar": "NFP — تقرير الوظائف الأمريكي",
        },
        "content": {
            "fr": (
                "<b>NFP = Non-Farm Payrolls (emplois hors agriculture)</b>\n\n"
                "Le premier vendredi de chaque mois, les USA publient combien de nouveaux\n"
                "emplois ont été créés. C'est l'une des <b>publications les plus importantes</b> !\n\n"
                "🟢 <b>NFP fort</b> (ex: +300K emplois) → les gens travaillent → l'économie va bien\n"
                "→ USD monte, marchés actions peuvent monter\n\n"
                "🔴 <b>NFP faible</b> (ex: +50K) → moins d'emplois → signal de faiblesse\n"
                "→ USD baisse, la Fed pourrait baisser les taux\n\n"
                "⚠️ <b>La surprise compte !</b>\n"
                "NFP attendu : +200K | NFP réel : +350K → gros mouvement USD haussier !\n\n"
                "💡 <b>Conseil :</b> Évite d'avoir des trades ouverts 30 min avant le NFP.\n"
                "Les spreads s'élargissent et la volatilité explose."
            ),
            "en": (
                "<b>NFP = Non-Farm Payrolls</b>\n\n"
                "Every first Friday of the month, the US publishes how many new\n"
                "jobs were created. It's one of the <b>most important releases!</b>\n\n"
                "🟢 <b>Strong NFP</b> (e.g. +300K jobs) → people are working → economy is healthy\n"
                "→ USD rises, stock markets may rise\n\n"
                "🔴 <b>Weak NFP</b> (e.g. +50K) → fewer jobs → sign of weakness\n"
                "→ USD falls, the Fed might cut rates\n\n"
                "⚠️ <b>The surprise is what matters!</b>\n"
                "NFP expected: +200K | NFP actual: +350K → big bullish USD move!\n\n"
                "💡 <b>Tip:</b> Avoid having open trades 30 min before NFP.\n"
                "Spreads widen and volatility explodes."
            ),
            "es": (
                "<b>NFP = Non-Farm Payrolls (empleos no agrícolas)</b>\n\n"
                "El primer viernes de cada mes, EE.UU. publica cuántos nuevos\n"
                "empleos se crearon. ¡Es uno de los <b>datos más importantes!</b>\n\n"
                "🟢 <b>NFP fuerte</b> (ej: +300K) → la gente trabaja → la economía va bien\n"
                "→ USD sube, bolsas pueden subir\n\n"
                "🔴 <b>NFP débil</b> (ej: +50K) → menos empleos → señal de debilidad\n"
                "→ USD baja, la Fed podría bajar tipos\n\n"
                "⚠️ <b>¡La sorpresa es lo que importa!</b>\n"
                "NFP esperado: +200K | NFP real: +350K → ¡gran movimiento alcista en USD!\n\n"
                "💡 <b>Consejo:</b> Evita tener operaciones abiertas 30 min antes del NFP.\n"
                "Los spreads se amplían y la volatilidad explota."
            ),
            "ar": (
                "<b>NFP = الوظائف غير الزراعية</b>\n\n"
                "في أول جمعة من كل شهر، تنشر الولايات المتحدة عدد الوظائف الجديدة\n"
                "التي تم إنشاؤها. إنه أحد <b>أهم البيانات الاقتصادية!</b>\n\n"
                "🟢 <b>NFP قوي</b> (مثال: +300K وظيفة) → الناس يعملون → الاقتصاد بصحة جيدة\n"
                "→ الدولار يرتفع، أسواق الأسهم قد ترتفع\n\n"
                "🔴 <b>NFP ضعيف</b> (مثال: +50K) → وظائف أقل → إشارة ضعف\n"
                "→ الدولار ينخفض، الفيد قد يخفض الفائدة\n\n"
                "⚠️ <b>المفاجأة هي ما يهم!</b>\n"
                "NFP المتوقع: +200K | NFP الفعلي: +350K → حركة صعودية كبيرة في الدولار!\n\n"
                "💡 <b>نصيحة:</b> تجنب وجود صفقات مفتوحة 30 دقيقة قبل NFP.\n"
                "الفوارق تتسع والتقلبات تنفجر."
            ),
        },
    },
    {
        "id": 5,
        "emoji": "🏦",
        "topic": {
            "fr": "Les taux d'intérêt — L'arme secrète des banques centrales",
            "en": "Interest rates — The central banks' secret weapon",
            "es": "Los tipos de interés — El arma secreta de los bancos centrales",
            "ar": "أسعار الفائدة — السلاح السري للبنوك المركزية",
        },
        "content": {
            "fr": (
                "<b>Le taux d'intérêt = le prix de l'argent</b>\n\n"
                "Quand une banque centrale monte ses taux, emprunter de l'argent devient plus cher.\n"
                "Ça ralentit l'économie et réduit l'inflation.\n\n"
                "<b>Taux élevé</b> 📈 → les investisseurs veulent acheter cette devise pour les rendements\n"
                "<b>Taux bas</b> 📉 → la devise moins attractive, l'argent va ailleurs\n\n"
                "🏛️ <b>Les grandes banques centrales :</b>\n"
                "• 🇺🇸 Fed (Federal Reserve) — pour le USD\n"
                "• 🇪🇺 BCE — pour l'EUR\n"
                "• 🇬🇧 BoE — pour le GBP\n"
                "• 🇯🇵 BoJ — pour le JPY\n\n"
                "💡 <b>Exemple :</b>\n"
                "Fed passe de 5% à 5.25% → USD monte → EUR/USD baisse\n"
                "Car les investisseurs préfèrent le dollar qui rapporte plus."
            ),
            "en": (
                "<b>Interest rate = the price of money</b>\n\n"
                "When a central bank raises rates, borrowing money becomes more expensive.\n"
                "This slows the economy and reduces inflation.\n\n"
                "<b>High rates</b> 📈 → investors want to buy that currency for the yield\n"
                "<b>Low rates</b> 📉 → currency less attractive, money goes elsewhere\n\n"
                "🏛️ <b>The major central banks:</b>\n"
                "• 🇺🇸 Fed (Federal Reserve) — for USD\n"
                "• 🇪🇺 ECB — for EUR\n"
                "• 🇬🇧 BoE — for GBP\n"
                "• 🇯🇵 BoJ — for JPY\n\n"
                "💡 <b>Example:</b>\n"
                "Fed goes from 5% to 5.25% → USD rises → EUR/USD falls\n"
                "Because investors prefer the dollar which pays more."
            ),
            "es": (
                "<b>El tipo de interés = el precio del dinero</b>\n\n"
                "Cuando un banco central sube los tipos, pedir dinero prestado se encarece.\n"
                "Esto frena la economía y reduce la inflación.\n\n"
                "<b>Tipos altos</b> 📈 → los inversores quieren comprar esa divisa por el rendimiento\n"
                "<b>Tipos bajos</b> 📉 → divisa menos atractiva, el dinero va a otro lado\n\n"
                "🏛️ <b>Los grandes bancos centrales:</b>\n"
                "• 🇺🇸 Fed (Reserva Federal) — para el USD\n"
                "• 🇪🇺 BCE — para el EUR\n"
                "• 🇬🇧 BoE — para el GBP\n"
                "• 🇯🇵 BoJ — para el JPY\n\n"
                "💡 <b>Ejemplo:</b>\n"
                "La Fed sube de 5% a 5.25% → USD sube → EUR/USD baja\n"
                "Porque los inversores prefieren el dólar que rinde más."
            ),
            "ar": (
                "<b>سعر الفائدة = ثمن المال</b>\n\n"
                "عندما يرفع البنك المركزي الفائدة، يصبح الاقتراض أكثر تكلفة.\n"
                "هذا يبطئ الاقتصاد ويقلل التضخم.\n\n"
                "<b>فائدة مرتفعة</b> 📈 → المستثمرون يريدون شراء تلك العملة للعوائد\n"
                "<b>فائدة منخفضة</b> 📉 → العملة أقل جاذبية، الأموال تذهب لمكان آخر\n\n"
                "🏛️ <b>البنوك المركزية الكبرى:</b>\n"
                "• 🇺🇸 الفيدرالي (Fed) — للدولار\n"
                "• 🇪🇺 البنك المركزي الأوروبي — لليورو\n"
                "• 🇬🇧 بنك إنجلترا — للجنيه\n"
                "• 🇯🇵 بنك اليابان — للين\n\n"
                "💡 <b>مثال:</b>\n"
                "الفيد يرفع من 5% إلى 5.25% → الدولار يرتفع → EUR/USD ينخفض\n"
                "لأن المستثمرين يفضلون الدولار الذي يدفع أكثر."
            ),
        },
    },
    {
        "id": 6,
        "emoji": "🦅",
        "topic": {
            "fr": "Hawkish vs Dovish — Le langage secret des banquiers",
            "en": "Hawkish vs Dovish — The secret language of bankers",
            "es": "Hawkish vs Dovish — El lenguaje secreto de los banqueros",
            "ar": "Hawkish مقابل Dovish — اللغة السرية للمصرفيين",
        },
        "content": {
            "fr": (
                "Les banquiers centraux ne disent jamais directement ce qu'ils vont faire.\n"
                "Ils utilisent des mots codés !\n\n"
                "🦅 <b>HAWKISH (faucon)</b> = ton agressif, veut combattre l'inflation\n"
                "→ Sous-entendu : <i>\"On va monter les taux\"</i>\n"
                "→ Effet : la devise <b>MONTE</b>\n\n"
                "🕊️ <b>DOVISH (colombe)</b> = ton doux, veut soutenir l'économie\n"
                "→ Sous-entendu : <i>\"On va baisser les taux\"</i>\n"
                "→ Effet : la devise <b>BAISSE</b>\n\n"
                "💡 <b>Comment les repérer ?</b>\n"
                "Hawkish : \"inflation persistante\", \"vigilance\", \"prêts à agir\"\n"
                "Dovish  : \"risques sur la croissance\", \"patient\", \"données dépendant\"\n\n"
                "⚡ <b>Exemple :</b>\n"
                "Le président de la Fed dit : <i>\"L'inflation reste trop haute, nous avons encore du travail à faire.\"</i>\n"
                "→ HAWKISH → USD monte instantanément."
            ),
            "en": (
                "Central bankers never say directly what they'll do.\n"
                "They use coded words!\n\n"
                "🦅 <b>HAWKISH</b> = aggressive tone, wants to fight inflation\n"
                "→ Meaning: <i>\"We're going to raise rates\"</i>\n"
                "→ Effect: currency <b>RISES</b>\n\n"
                "🕊️ <b>DOVISH</b> = soft tone, wants to support the economy\n"
                "→ Meaning: <i>\"We're going to cut rates\"</i>\n"
                "→ Effect: currency <b>FALLS</b>\n\n"
                "💡 <b>How to spot them?</b>\n"
                "Hawkish: \"persistent inflation\", \"vigilant\", \"ready to act\"\n"
                "Dovish:  \"growth risks\", \"patient\", \"data dependent\"\n\n"
                "⚡ <b>Example:</b>\n"
                "Fed chair says: <i>\"Inflation remains too high, we have more work to do.\"</i>\n"
                "→ HAWKISH → USD rises instantly."
            ),
            "es": (
                "Los banqueros centrales nunca dicen directamente lo que harán.\n"
                "¡Usan palabras en código!\n\n"
                "🦅 <b>HAWKISH (halcón)</b> = tono agresivo, quiere combatir la inflación\n"
                "→ Significado: <i>\"Vamos a subir los tipos\"</i>\n"
                "→ Efecto: la divisa <b>SUBE</b>\n\n"
                "🕊️ <b>DOVISH (paloma)</b> = tono suave, quiere apoyar la economía\n"
                "→ Significado: <i>\"Vamos a bajar los tipos\"</i>\n"
                "→ Efecto: la divisa <b>BAJA</b>\n\n"
                "💡 <b>¿Cómo reconocerlos?</b>\n"
                "Hawkish: \"inflación persistente\", \"vigilancia\", \"listos para actuar\"\n"
                "Dovish:  \"riesgos de crecimiento\", \"paciencia\", \"dependientes de datos\"\n\n"
                "⚡ <b>Ejemplo:</b>\n"
                "El presidente de la Fed dice: <i>\"La inflación sigue siendo demasiado alta, aún tenemos trabajo que hacer.\"</i>\n"
                "→ HAWKISH → USD sube al instante."
            ),
            "ar": (
                "المصرفيون المركزيون لا يقولون مباشرة ما سيفعلونه.\n"
                "يستخدمون كلمات مشفرة!\n\n"
                "🦅 <b>HAWKISH (صقري)</b> = نبرة عدوانية، يريد محاربة التضخم\n"
                "→ المعنى: <i>\"سنرفع أسعار الفائدة\"</i>\n"
                "→ التأثير: العملة <b>ترتفع</b>\n\n"
                "🕊️ <b>DOVISH (حمامي)</b> = نبرة هادئة، يريد دعم الاقتصاد\n"
                "→ المعنى: <i>\"سنخفض أسعار الفائدة\"</i>\n"
                "→ التأثير: العملة <b>تنخفض</b>\n\n"
                "💡 <b>كيف تتعرف عليهم؟</b>\n"
                "صقري: \"تضخم مستمر\"، \"يقظة\"، \"مستعدون للتحرك\"\n"
                "حمامي: \"مخاطر النمو\"، \"صبر\"، \"نعتمد على البيانات\"\n\n"
                "⚡ <b>مثال:</b>\n"
                "رئيس الفيد يقول: <i>\"التضخم لا يزال مرتفعاً جداً، ولا يزال أمامنا عمل.\"</i>\n"
                "→ صقري → الدولار يرتفع فوراً."
            ),
        },
    },
    {
        "id": 7,
        "emoji": "📊",
        "topic": {
            "fr": "Le PMI — Le thermomètre des entreprises",
            "en": "PMI — The business thermometer",
            "es": "El PMI — El termómetro empresarial",
            "ar": "PMI — ميزان حرارة الأعمال",
        },
        "content": {
            "fr": (
                "<b>PMI = Purchasing Managers Index</b>\n"
                "(Indice des directeurs d'achats)\n\n"
                "Chaque mois, on demande aux responsables d'entreprises :\n"
                "<i>\"Ça va mieux ou moins bien qu'avant ?\"</i>\n\n"
                "📏 <b>La règle magique :</b>\n"
                "• PMI > 50 → expansion (les affaires vont bien) 🟢\n"
                "• PMI < 50 → contraction (les affaires vont mal) 🔴\n"
                "• PMI = 50 → neutre\n\n"
                "Il y a deux types :\n"
                "🏭 <b>PMI Manufacturier</b> — usines, production\n"
                "🛍️ <b>PMI Services</b> — restaurants, banques, tech (plus important !)\n\n"
                "💡 <b>Exemple :</b>\n"
                "PMI Services US sort à 55 (attendu 52) → bonne santé → USD et actions montent."
            ),
            "en": (
                "<b>PMI = Purchasing Managers Index</b>\n\n"
                "Every month, business managers are asked:\n"
                "<i>\"Are things better or worse than before?\"</i>\n\n"
                "📏 <b>The magic rule:</b>\n"
                "• PMI > 50 → expansion (business is good) 🟢\n"
                "• PMI < 50 → contraction (business is bad) 🔴\n"
                "• PMI = 50 → neutral\n\n"
                "Two types:\n"
                "🏭 <b>Manufacturing PMI</b> — factories, production\n"
                "🛍️ <b>Services PMI</b> — restaurants, banks, tech (more important!)\n\n"
                "💡 <b>Example:</b>\n"
                "US Services PMI comes in at 55 (expected 52) → healthy economy → USD and stocks rise."
            ),
            "es": (
                "<b>PMI = Índice de Gestores de Compras</b>\n\n"
                "Cada mes, se pregunta a los directivos de empresas:\n"
                "<i>\"¿Las cosas van mejor o peor que antes?\"</i>\n\n"
                "📏 <b>La regla mágica:</b>\n"
                "• PMI > 50 → expansión (los negocios van bien) 🟢\n"
                "• PMI < 50 → contracción (los negocios van mal) 🔴\n"
                "• PMI = 50 → neutral\n\n"
                "Dos tipos:\n"
                "🏭 <b>PMI Manufacturero</b> — fábricas, producción\n"
                "🛍️ <b>PMI Servicios</b> — restaurantes, bancos, tech (¡más importante!)\n\n"
                "💡 <b>Ejemplo:</b>\n"
                "PMI Servicios EE.UU. sale en 55 (esperado 52) → economía sana → USD y acciones suben."
            ),
            "ar": (
                "<b>PMI = مؤشر مديري المشتريات</b>\n\n"
                "كل شهر، يُسأل مديرو الأعمال:\n"
                "<i>\"هل الأمور أفضل أم أسوأ مما كانت عليه؟\"</i>\n\n"
                "📏 <b>القاعدة السحرية:</b>\n"
                "• PMI > 50 → توسع (الأعمال تسير بشكل جيد) 🟢\n"
                "• PMI < 50 → انكماش (الأعمال تسير بشكل سيء) 🔴\n"
                "• PMI = 50 → محايد\n\n"
                "نوعان:\n"
                "🏭 <b>PMI التصنيعي</b> — المصانع والإنتاج\n"
                "🛍️ <b>PMI الخدمات</b> — المطاعم والبنوك والتقنية (الأكثر أهمية!)\n\n"
                "💡 <b>مثال:</b>\n"
                "PMI الخدمات الأمريكي يصدر بـ 55 (المتوقع 52) → اقتصاد صحي → الدولار والأسهم ترتفع."
            ),
        },
    },
    {
        "id": 8,
        "emoji": "💰",
        "topic": {
            "fr": "Le DXY — La force du dollar en un chiffre",
            "en": "The DXY — Dollar strength in one number",
            "es": "El DXY — La fortaleza del dólar en un número",
            "ar": "DXY — قوة الدولار في رقم واحد",
        },
        "content": {
            "fr": (
                "<b>DXY = Dollar Index</b>\n\n"
                "C'est une balance qui compare le dollar contre un panier de 6 devises :\n"
                "EUR (57%) · JPY (13%) · GBP (12%) · CAD (9%) · SEK (4%) · CHF (3%)\n\n"
                "📈 <b>DXY monte</b> → le dollar est fort\n"
                "→ EUR/USD baisse · GBP/USD baisse · L'or baisse souvent\n\n"
                "📉 <b>DXY baisse</b> → le dollar est faible\n"
                "→ EUR/USD monte · Or monte · NAS100 peut monter\n\n"
                "🎯 <b>Pourquoi c'est utile ?</b>\n"
                "Avant d'ouvrir un trade sur EUR/USD ou GBP/USD,\n"
                "regarde le DXY pour confirmer le biais directeur.\n\n"
                "💡 <b>Règle simple :</b>\n"
                "DXY ↑ → vends EUR/USD · DXY ↓ → achètes EUR/USD"
            ),
            "en": (
                "<b>DXY = US Dollar Index</b>\n\n"
                "It's a scale that compares the dollar against a basket of 6 currencies:\n"
                "EUR (57%) · JPY (13%) · GBP (12%) · CAD (9%) · SEK (4%) · CHF (3%)\n\n"
                "📈 <b>DXY rises</b> → dollar is strong\n"
                "→ EUR/USD falls · GBP/USD falls · Gold often falls\n\n"
                "📉 <b>DXY falls</b> → dollar is weak\n"
                "→ EUR/USD rises · Gold rises · NAS100 may rise\n\n"
                "🎯 <b>Why is it useful?</b>\n"
                "Before opening a trade on EUR/USD or GBP/USD,\n"
                "check the DXY to confirm your directional bias.\n\n"
                "💡 <b>Simple rule:</b>\n"
                "DXY ↑ → sell EUR/USD · DXY ↓ → buy EUR/USD"
            ),
            "es": (
                "<b>DXY = Índice del Dólar</b>\n\n"
                "Es una balanza que compara el dólar contra una cesta de 6 divisas:\n"
                "EUR (57%) · JPY (13%) · GBP (12%) · CAD (9%) · SEK (4%) · CHF (3%)\n\n"
                "📈 <b>DXY sube</b> → el dólar es fuerte\n"
                "→ EUR/USD baja · GBP/USD baja · El oro a menudo baja\n\n"
                "📉 <b>DXY baja</b> → el dólar es débil\n"
                "→ EUR/USD sube · Oro sube · NAS100 puede subir\n\n"
                "🎯 <b>¿Por qué es útil?</b>\n"
                "Antes de abrir un trade en EUR/USD o GBP/USD,\n"
                "mira el DXY para confirmar el sesgo direccional.\n\n"
                "💡 <b>Regla simple:</b>\n"
                "DXY ↑ → vende EUR/USD · DXY ↓ → compra EUR/USD"
            ),
            "ar": (
                "<b>DXY = مؤشر الدولار الأمريكي</b>\n\n"
                "هو ميزان يقارن الدولار بسلة من 6 عملات:\n"
                "اليورو (57%) · الين (13%) · الجنيه (12%) · الكندي (9%) · الكرونة السويدية (4%) · الفرنك السويسري (3%)\n\n"
                "📈 <b>DXY يرتفع</b> → الدولار قوي\n"
                "→ EUR/USD ينخفض · GBP/USD ينخفض · الذهب غالباً ينخفض\n\n"
                "📉 <b>DXY ينخفض</b> → الدولار ضعيف\n"
                "→ EUR/USD يرتفع · الذهب يرتفع · NAS100 قد يرتفع\n\n"
                "🎯 <b>لماذا هو مفيد؟</b>\n"
                "قبل فتح صفقة على EUR/USD أو GBP/USD،\n"
                "تحقق من DXY لتأكيد الاتجاه العام.\n\n"
                "💡 <b>قاعدة بسيطة:</b>\n"
                "DXY ↑ → بيع EUR/USD · DXY ↓ → شراء EUR/USD"
            ),
        },
    },
    {
        "id": 9,
        "emoji": "🥇",
        "topic": {
            "fr": "L'or — Le refuge quand tout va mal",
            "en": "Gold — The refuge when everything goes wrong",
            "es": "El oro — El refugio cuando todo va mal",
            "ar": "الذهب — الملاذ الآمن عندما تسوء الأمور",
        },
        "content": {
            "fr": (
                "<b>L'or (XAU/USD) = valeur refuge</b>\n\n"
                "Depuis des millénaires, les humains font confiance à l'or.\n"
                "Quand il y a de la peur dans les marchés, tout le monde achète de l'or.\n\n"
                "📈 <b>L'or monte quand :</b>\n"
                "• Il y a une crise (guerre, récession, crash)\n"
                "• Le dollar baisse (DXY ↓)\n"
                "• La Fed baisse les taux (moins d'intérêt sur le cash)\n"
                "• L'inflation monte (l'or protège la valeur)\n\n"
                "📉 <b>L'or baisse quand :</b>\n"
                "• Le dollar monte (DXY ↑)\n"
                "• La Fed monte les taux (le cash rapporte plus)\n"
                "• L'économie est forte et les gens prennent des risques\n\n"
                "💡 <b>Relation clé :</b>\n"
                "Or et USD ont souvent une corrélation <b>inverse</b> (−0.7 à −0.9)."
            ),
            "en": (
                "<b>Gold (XAU/USD) = safe haven asset</b>\n\n"
                "For thousands of years, humans have trusted gold.\n"
                "When there's fear in the markets, everyone buys gold.\n\n"
                "📈 <b>Gold rises when:</b>\n"
                "• There's a crisis (war, recession, crash)\n"
                "• The dollar falls (DXY ↓)\n"
                "• The Fed cuts rates (less interest on cash)\n"
                "• Inflation rises (gold protects value)\n\n"
                "📉 <b>Gold falls when:</b>\n"
                "• The dollar rises (DXY ↑)\n"
                "• The Fed raises rates (cash pays more)\n"
                "• Economy is strong and people take risks\n\n"
                "💡 <b>Key relationship:</b>\n"
                "Gold and USD often have an <b>inverse</b> correlation (−0.7 to −0.9)."
            ),
            "es": (
                "<b>El oro (XAU/USD) = activo refugio</b>\n\n"
                "Durante milenios, los humanos han confiado en el oro.\n"
                "Cuando hay miedo en los mercados, todos compran oro.\n\n"
                "📈 <b>El oro sube cuando:</b>\n"
                "• Hay una crisis (guerra, recesión, crash)\n"
                "• El dólar cae (DXY ↓)\n"
                "• La Fed baja tipos (menos interés en el efectivo)\n"
                "• La inflación sube (el oro protege el valor)\n\n"
                "📉 <b>El oro baja cuando:</b>\n"
                "• El dólar sube (DXY ↑)\n"
                "• La Fed sube tipos (el efectivo rinde más)\n"
                "• La economía está fuerte y la gente asume riesgos\n\n"
                "💡 <b>Relación clave:</b>\n"
                "El oro y el USD suelen tener una correlación <b>inversa</b> (−0.7 a −0.9)."
            ),
            "ar": (
                "<b>الذهب (XAU/USD) = أصل الملاذ الآمن</b>\n\n"
                "منذ آلاف السنين، وثق البشر بالذهب.\n"
                "عندما يسود الخوف في الأسواق، يشتري الجميع الذهب.\n\n"
                "📈 <b>الذهب يرتفع عندما:</b>\n"
                "• هناك أزمة (حرب، ركود، انهيار)\n"
                "• الدولار ينخفض (DXY ↓)\n"
                "• الفيد يخفض الفائدة (أقل عائد على النقد)\n"
                "• التضخم يرتفع (الذهب يحمي القيمة)\n\n"
                "📉 <b>الذهب ينخفض عندما:</b>\n"
                "• الدولار يرتفع (DXY ↑)\n"
                "• الفيد يرفع الفائدة (النقد يدفع أكثر)\n"
                "• الاقتصاد قوي والناس يتحملون المخاطر\n\n"
                "💡 <b>العلاقة الأساسية:</b>\n"
                "الذهب والدولار غالباً لديهم ارتباط <b>عكسي</b> (من −0.7 إلى −0.9)."
            ),
        },
    },
    {
        "id": 10,
        "emoji": "📉",
        "topic": {
            "fr": "Risk-On / Risk-Off — L'humeur des marchés",
            "en": "Risk-On / Risk-Off — Market mood",
            "es": "Risk-On / Risk-Off — El estado de ánimo del mercado",
            "ar": "Risk-On / Risk-Off — مزاج الأسواق",
        },
        "content": {
            "fr": (
                "Les marchés ont deux humeurs principales :\n\n"
                "😎 <b>RISK-ON</b> — \"Tout va bien, je prends des risques !\"\n"
                "→ Les gens achètent des actions (NAS100, US500)\n"
                "→ Ils vendent l'or et le JPY (qui baissent)\n"
                "→ Les devises émergentes montent\n\n"
                "😱 <b>RISK-OFF</b> — \"Panique ! Je mets mon argent en sécurité !\"\n"
                "→ Les gens achètent l'or 🥇, le JPY 🇯🇵, le CHF 🇨🇭\n"
                "→ Ils vendent les actions (NAS100 baisse)\n"
                "→ Le dollar peut monter\n\n"
                "💡 <b>Déclencheurs Risk-Off :</b>\n"
                "Guerre · Crash · Mauvais NFP · Panique bancaire · Récession\n\n"
                "🎯 <b>Conseil :</b>\n"
                "Quand tu vois l'or et le JPY monter en même temps → Risk-Off activé.\n"
                "Ne trade pas contre le sentiment dominant !"
            ),
            "en": (
                "Markets have two main moods:\n\n"
                "😎 <b>RISK-ON</b> — \"Everything's fine, I'll take risks!\"\n"
                "→ People buy stocks (NAS100, US500)\n"
                "→ They sell gold and JPY (which fall)\n"
                "→ Emerging market currencies rise\n\n"
                "😱 <b>RISK-OFF</b> — \"Panic! Put my money somewhere safe!\"\n"
                "→ People buy gold 🥇, JPY 🇯🇵, CHF 🇨🇭\n"
                "→ They sell stocks (NAS100 falls)\n"
                "→ Dollar may rise\n\n"
                "💡 <b>Risk-Off triggers:</b>\n"
                "War · Crash · Bad NFP · Banking panic · Recession\n\n"
                "🎯 <b>Tip:</b>\n"
                "When you see gold and JPY rising together → Risk-Off activated.\n"
                "Don't trade against the dominant sentiment!"
            ),
            "es": (
                "Los mercados tienen dos estados de ánimo principales:\n\n"
                "😎 <b>RISK-ON</b> — \"¡Todo va bien, asumo riesgos!\"\n"
                "→ La gente compra acciones (NAS100, US500)\n"
                "→ Venden oro y JPY (que bajan)\n"
                "→ Las divisas emergentes suben\n\n"
                "😱 <b>RISK-OFF</b> — \"¡Pánico! ¡Pongo mi dinero a salvo!\"\n"
                "→ La gente compra oro 🥇, JPY 🇯🇵, CHF 🇨🇭\n"
                "→ Venden acciones (NAS100 baja)\n"
                "→ El dólar puede subir\n\n"
                "💡 <b>Desencadenantes Risk-Off:</b>\n"
                "Guerra · Crash · NFP malo · Pánico bancario · Recesión\n\n"
                "🎯 <b>Consejo:</b>\n"
                "Cuando veas el oro y el JPY subiendo juntos → Risk-Off activado.\n"
                "¡No tradees contra el sentimiento dominante!"
            ),
            "ar": (
                "للأسواق مزاجان رئيسيان:\n\n"
                "😎 <b>RISK-ON</b> — \"كل شيء بخير، سأتحمل المخاطر!\"\n"
                "→ الناس يشترون الأسهم (NAS100، US500)\n"
                "→ يبيعون الذهب والين (التي تنخفض)\n"
                "→ عملات الأسواق الناشئة ترتفع\n\n"
                "😱 <b>RISK-OFF</b> — \"هلع! ضع أموالي في مكان آمن!\"\n"
                "→ الناس يشترون الذهب 🥇، الين 🇯🇵، الفرنك السويسري 🇨🇭\n"
                "→ يبيعون الأسهم (NAS100 ينخفض)\n"
                "→ الدولار قد يرتفع\n\n"
                "💡 <b>محفزات Risk-Off:</b>\n"
                "حرب · انهيار · NFP سيء · ذعر مصرفي · ركود\n\n"
                "🎯 <b>نصيحة:</b>\n"
                "عندما ترى الذهب والين يرتفعان معاً → Risk-Off تم تفعيله.\n"
                "لا تتداول ضد المشاعر السائدة!"
            ),
        },
    },
    {
        "id": 11,
        "emoji": "🛒",
        "topic": {
            "fr": "Les ventes au détail — Ce que les gens dépensent",
            "en": "Retail Sales — What people are spending",
            "es": "Las ventas minoristas — Lo que la gente gasta",
            "ar": "مبيعات التجزئة — ما ينفقه الناس",
        },
        "content": {
            "fr": (
                "<b>Retail Sales = Ventes au détail</b>\n\n"
                "Combien les gens ont-ils dépensé dans les magasins ce mois-ci ?\n"
                "C'est simple : si les gens dépensent, l'économie va bien !\n\n"
                "🟢 <b>Ventes élevées</b> → consommation forte → économie en bonne santé\n"
                "→ USD monte, actions montent\n\n"
                "🔴 <b>Ventes faibles</b> → les consommateurs serrent la ceinture\n"
                "→ Signal de ralentissement → USD peut baisser\n\n"
                "📊 <b>Poids dans l'économie US :</b>\n"
                "La consommation représente <b>70%</b> du PIB américain !\n"
                "C'est pourquoi ce chiffre est très suivi.\n\n"
                "💡 <b>Exemple :</b>\n"
                "Retail Sales US : +1.2% (attendu +0.5%) → consommateur solide\n"
                "→ USD monte, NAS100 monte (les entreprises vendent plus)."
            ),
            "en": (
                "<b>Retail Sales</b>\n\n"
                "How much did people spend in stores this month?\n"
                "Simple: if people are spending, the economy is doing well!\n\n"
                "🟢 <b>High sales</b> → strong consumption → healthy economy\n"
                "→ USD rises, stocks rise\n\n"
                "🔴 <b>Low sales</b> → consumers tightening their belts\n"
                "→ Sign of slowdown → USD may fall\n\n"
                "📊 <b>Weight in the US economy:</b>\n"
                "Consumer spending represents <b>70%</b> of US GDP!\n"
                "That's why this number is closely watched.\n\n"
                "💡 <b>Example:</b>\n"
                "US Retail Sales: +1.2% (expected +0.5%) → strong consumer\n"
                "→ USD rises, NAS100 rises (companies sell more)."
            ),
            "es": (
                "<b>Ventas minoristas</b>\n\n"
                "¿Cuánto gastó la gente en las tiendas este mes?\n"
                "Sencillo: ¡si la gente gasta, la economía va bien!\n\n"
                "🟢 <b>Ventas altas</b> → consumo fuerte → economía sana\n"
                "→ USD sube, acciones suben\n\n"
                "🔴 <b>Ventas bajas</b> → los consumidores se aprietan el cinturón\n"
                "→ Señal de desaceleración → USD puede bajar\n\n"
                "📊 <b>Peso en la economía de EE.UU.:</b>\n"
                "El consumo representa el <b>70%</b> del PIB de EE.UU.!\n"
                "Por eso este dato está muy vigilado.\n\n"
                "💡 <b>Ejemplo:</b>\n"
                "Ventas minoristas EE.UU.: +1.2% (esperado +0.5%) → consumidor sólido\n"
                "→ USD sube, NAS100 sube (las empresas venden más)."
            ),
            "ar": (
                "<b>مبيعات التجزئة</b>\n\n"
                "كم أنفق الناس في المتاجر هذا الشهر؟\n"
                "بسيط: إذا كان الناس ينفقون، فالاقتصاد بخير!\n\n"
                "🟢 <b>مبيعات مرتفعة</b> → استهلاك قوي → اقتصاد صحي\n"
                "→ الدولار يرتفع، الأسهم ترتفع\n\n"
                "🔴 <b>مبيعات منخفضة</b> → المستهلكون يشددون الحزام\n"
                "→ إشارة تباطؤ → الدولار قد ينخفض\n\n"
                "📊 <b>الوزن في الاقتصاد الأمريكي:</b>\n"
                "الإنفاق الاستهلاكي يمثل <b>70%</b> من الناتج المحلي الإجمالي الأمريكي!\n"
                "لهذا يُراقَب هذا الرقم عن كثب.\n\n"
                "💡 <b>مثال:</b>\n"
                "مبيعات التجزئة الأمريكية: +1.2% (المتوقع +0.5%) → مستهلك قوي\n"
                "→ الدولار يرتفع، NAS100 يرتفع (الشركات تبيع أكثر)."
            ),
        },
    },
    {
        "id": 12,
        "emoji": "📅",
        "topic": {
            "fr": "Le calendrier économique — Ton agenda de trader",
            "en": "The economic calendar — Your trading agenda",
            "es": "El calendario económico — Tu agenda de trader",
            "ar": "التقويم الاقتصادي — أجندتك كمتداول",
        },
        "content": {
            "fr": (
                "<b>Le calendrier économique</b> liste toutes les publications importantes\n"
                "avec leur date, heure et impact attendu.\n\n"
                "🔴 <b>Impact ÉLEVÉ</b> — peut bouger le marché de 50+ pips\n"
                "   ex: NFP, CPI, décisions de la Fed\n\n"
                "🟡 <b>Impact MOYEN</b> — mouvement modéré\n"
                "   ex: PMI, ventes au détail\n\n"
                "⚪ <b>Impact FAIBLE</b> — peu d'effet en général\n\n"
                "⚠️ <b>3 règles de base :</b>\n"
                "1. Vérifie le calendrier AVANT d'ouvrir un trade\n"
                "2. Si un événement rouge arrive dans 30 min → évite d'entrer\n"
                "3. Après la publication : la direction initiale peut être fausse\n"
                "   (\"buy the rumor, sell the news\")\n\n"
                "💡 Utilise <code>/day</code> ou <code>/week</code> pour voir le calendrier directement ici !"
            ),
            "en": (
                "<b>The economic calendar</b> lists all major releases\n"
                "with their date, time, and expected impact.\n\n"
                "🔴 <b>HIGH Impact</b> — can move the market 50+ pips\n"
                "   e.g.: NFP, CPI, Fed decisions\n\n"
                "🟡 <b>MEDIUM Impact</b> — moderate movement\n"
                "   e.g.: PMI, retail sales\n\n"
                "⚪ <b>LOW Impact</b> — usually little effect\n\n"
                "⚠️ <b>3 basic rules:</b>\n"
                "1. Check the calendar BEFORE opening a trade\n"
                "2. If a red event is coming in 30 min → avoid entering\n"
                "3. After the release: the initial direction may be wrong\n"
                "   (\"buy the rumor, sell the news\")\n\n"
                "💡 Use <code>/day</code> or <code>/week</code> to see the calendar right here!"
            ),
            "es": (
                "<b>El calendario económico</b> lista todas las publicaciones importantes\n"
                "con su fecha, hora e impacto esperado.\n\n"
                "🔴 <b>Impacto ALTO</b> — puede mover el mercado 50+ pips\n"
                "   ej: NFP, IPC, decisiones de la Fed\n\n"
                "🟡 <b>Impacto MEDIO</b> — movimiento moderado\n"
                "   ej: PMI, ventas minoristas\n\n"
                "⚪ <b>Impacto BAJO</b> — generalmente poco efecto\n\n"
                "⚠️ <b>3 reglas básicas:</b>\n"
                "1. Revisa el calendario ANTES de abrir un trade\n"
                "2. Si hay un evento rojo en 30 min → evita entrar\n"
                "3. Después de la publicación: la dirección inicial puede ser falsa\n"
                "   (\"compra el rumor, vende la noticia\")\n\n"
                "💡 ¡Usa <code>/day</code> o <code>/week</code> para ver el calendario aquí mismo!"
            ),
            "ar": (
                "<b>التقويم الاقتصادي</b> يدرج جميع الإصدارات المهمة\n"
                "بتاريخها وتوقيتها وتأثيرها المتوقع.\n\n"
                "🔴 <b>تأثير عالٍ</b> — يمكن أن يحرك السوق 50+ نقطة\n"
                "   مثال: NFP، CPI، قرارات الفيد\n\n"
                "🟡 <b>تأثير متوسط</b> — حركة معتدلة\n"
                "   مثال: PMI، مبيعات التجزئة\n\n"
                "⚪ <b>تأثير منخفض</b> — عادةً تأثير قليل\n\n"
                "⚠️ <b>3 قواعد أساسية:</b>\n"
                "1. تحقق من التقويم قبل فتح أي صفقة\n"
                "2. إذا كان هناك حدث أحمر خلال 30 دقيقة → تجنب الدخول\n"
                "3. بعد الإصدار: الاتجاه الأولي قد يكون خاطئاً\n"
                "   (\"اشترِ الشائعة، بع الحقيقة\")\n\n"
                "💡 استخدم <code>/day</code> أو <code>/week</code> لرؤية التقويم هنا مباشرة!"
            ),
        },
    },
    {
        "id": 13,
        "emoji": "🌐",
        "topic": {
            "fr": "La géopolitique — Quand le monde change les marchés",
            "en": "Geopolitics — When the world changes markets",
            "es": "La geopolítica — Cuando el mundo cambia los mercados",
            "ar": "الجيوسياسة — عندما يغير العالم الأسواق",
        },
        "content": {
            "fr": (
                "Les marchés ne réagissent pas qu'aux chiffres économiques.\n"
                "Les événements <b>géopolitiques</b> peuvent tout changer en quelques secondes.\n\n"
                "⚔️ <b>Guerre / Conflit :</b>\n"
                "→ Or monte · Pétrole monte · Actions baissent\n"
                "→ USD peut monter (valeur refuge)\n\n"
                "🤝 <b>Accord de paix / Trêve :</b>\n"
                "→ Actions montent · Or baisse\n\n"
                "🚢 <b>Blocage commercial / Sanctions :</b>\n"
                "→ Devises des pays concernés s'effondrent\n\n"
                "🗳️ <b>Élections :</b>\n"
                "→ Incertitude = volatilité = méfiance\n"
                "→ Victoire inattendue → fort mouvement de devise\n\n"
                "💡 <b>Règle clé :</b>\n"
                "En période de crise géopolitique → <b>cherche l'or et évite les risques.</b>\n"
                "Le marché ne sait pas gérer l'incertitude — il panique d'abord."
            ),
            "en": (
                "Markets don't just react to economic numbers.\n"
                "<b>Geopolitical</b> events can change everything in seconds.\n\n"
                "⚔️ <b>War / Conflict:</b>\n"
                "→ Gold rises · Oil rises · Stocks fall\n"
                "→ USD may rise (safe haven)\n\n"
                "🤝 <b>Peace deal / Truce:</b>\n"
                "→ Stocks rise · Gold falls\n\n"
                "🚢 <b>Trade blockade / Sanctions:</b>\n"
                "→ Currencies of affected countries collapse\n\n"
                "🗳️ <b>Elections:</b>\n"
                "→ Uncertainty = volatility = mistrust\n"
                "→ Unexpected winner → big currency move\n\n"
                "💡 <b>Key rule:</b>\n"
                "During geopolitical crises → <b>look for gold and avoid risk.</b>\n"
                "The market can't handle uncertainty — it panics first."
            ),
            "es": (
                "Los mercados no solo reaccionan a los datos económicos.\n"
                "Los eventos <b>geopolíticos</b> pueden cambiarlo todo en segundos.\n\n"
                "⚔️ <b>Guerra / Conflicto:</b>\n"
                "→ Oro sube · Petróleo sube · Acciones bajan\n"
                "→ USD puede subir (refugio seguro)\n\n"
                "🤝 <b>Acuerdo de paz / Tregua:</b>\n"
                "→ Acciones suben · Oro baja\n\n"
                "🚢 <b>Bloqueo comercial / Sanciones:</b>\n"
                "→ Divisas de los países afectados se desploman\n\n"
                "🗳️ <b>Elecciones:</b>\n"
                "→ Incertidumbre = volatilidad = desconfianza\n"
                "→ Ganador inesperado → gran movimiento de divisa\n\n"
                "💡 <b>Regla clave:</b>\n"
                "En crisis geopolítica → <b>busca el oro y evita el riesgo.</b>\n"
                "El mercado no puede manejar la incertidumbre — primero entra en pánico."
            ),
            "ar": (
                "الأسواق لا تتفاعل فقط مع الأرقام الاقتصادية.\n"
                "الأحداث <b>الجيوسياسية</b> يمكن أن تغير كل شيء في ثوانٍ.\n\n"
                "⚔️ <b>حرب / نزاع:</b>\n"
                "→ الذهب يرتفع · النفط يرتفع · الأسهم تنخفض\n"
                "→ الدولار قد يرتفع (ملاذ آمن)\n\n"
                "🤝 <b>اتفاقية سلام / هدنة:</b>\n"
                "→ الأسهم ترتفع · الذهب ينخفض\n\n"
                "🚢 <b>حصار تجاري / عقوبات:</b>\n"
                "→ عملات الدول المتضررة تنهار\n\n"
                "🗳️ <b>انتخابات:</b>\n"
                "→ غموض = تقلبات = ريبة\n"
                "→ فائز غير متوقع → حركة عملة كبيرة\n\n"
                "💡 <b>القاعدة الأساسية:</b>\n"
                "خلال الأزمات الجيوسياسية → <b>ابحث عن الذهب وتجنب المخاطر.</b>\n"
                "السوق لا يمكنه التعامل مع عدم اليقين — فهو يذعر أولاً."
            ),
        },
    },
    {
        "id": 14,
        "emoji": "📈",
        "topic": {
            "fr": "Le chômage — Mesure du marché de l'emploi",
            "en": "Unemployment — Measuring the job market",
            "es": "El desempleo — Midiendo el mercado laboral",
            "ar": "البطالة — قياس سوق العمل",
        },
        "content": {
            "fr": (
                "<b>Taux de chômage</b> = % de personnes qui cherchent du travail sans en trouver\n\n"
                "🟢 <b>Chômage bas</b> → les gens travaillent → ils dépensent → économie forte\n"
                "🔴 <b>Chômage haut</b> → moins de revenus → moins de dépenses → économie faible\n\n"
                "<b>Indicateurs connexes :</b>\n"
                "• <b>Initial Jobless Claims</b> (chaque jeudi) — nouvelles demandes d'allocations\n"
                "  Si ça monte → de plus en plus de gens perdent leur emploi\n\n"
                "• <b>Average Hourly Earnings</b> (avec le NFP) — les salaires montent ?\n"
                "  Si oui → les gens dépensent plus → peut alimenter l'inflation\n\n"
                "💡 <b>Paradoxe fréquent :</b>\n"
                "Un chômage trop BAS peut faire monter l'inflation\n"
                "(les employeurs payent plus pour attirer les travailleurs → les prix montent)\n"
                "→ La Fed monte les taux pour refroidir."
            ),
            "en": (
                "<b>Unemployment rate</b> = % of people looking for work but unable to find it\n\n"
                "🟢 <b>Low unemployment</b> → people working → spending → strong economy\n"
                "🔴 <b>High unemployment</b> → less income → less spending → weak economy\n\n"
                "<b>Related indicators:</b>\n"
                "• <b>Initial Jobless Claims</b> (every Thursday) — new benefit applications\n"
                "  If rising → more and more people losing their jobs\n\n"
                "• <b>Average Hourly Earnings</b> (with NFP) — are wages rising?\n"
                "  If yes → people spend more → can fuel inflation\n\n"
                "💡 <b>Common paradox:</b>\n"
                "Unemployment too LOW can drive inflation UP\n"
                "(employers pay more to attract workers → prices rise)\n"
                "→ Fed raises rates to cool things down."
            ),
            "es": (
                "<b>Tasa de desempleo</b> = % de personas buscando trabajo sin encontrarlo\n\n"
                "🟢 <b>Desempleo bajo</b> → la gente trabaja → gasta → economía fuerte\n"
                "🔴 <b>Desempleo alto</b> → menos ingresos → menos gasto → economía débil\n\n"
                "<b>Indicadores relacionados:</b>\n"
                "• <b>Initial Jobless Claims</b> (cada jueves) — nuevas solicitudes de subsidio\n"
                "  Si sube → cada vez más gente pierde su empleo\n\n"
                "• <b>Average Hourly Earnings</b> (con el NFP) — ¿los salarios suben?\n"
                "  Si es así → la gente gasta más → puede alimentar la inflación\n\n"
                "💡 <b>Paradoja frecuente:</b>\n"
                "Un desempleo demasiado BAJO puede hacer subir la inflación\n"
                "(los empleadores pagan más para atraer trabajadores → los precios suben)\n"
                "→ La Fed sube tipos para enfriar."
            ),
            "ar": (
                "<b>معدل البطالة</b> = نسبة الأشخاص الباحثين عن عمل وغير القادرين على إيجاده\n\n"
                "🟢 <b>بطالة منخفضة</b> → الناس يعملون → ينفقون → اقتصاد قوي\n"
                "🔴 <b>بطالة مرتفعة</b> → دخل أقل → إنفاق أقل → اقتصاد ضعيف\n\n"
                "<b>مؤشرات ذات صلة:</b>\n"
                "• <b>Initial Jobless Claims</b> (كل خميس) — طلبات إعانة البطالة الجديدة\n"
                "  إذا ارتفعت → المزيد من الناس يفقدون وظائفهم\n\n"
                "• <b>Average Hourly Earnings</b> (مع NFP) — هل الأجور ترتفع؟\n"
                "  إذا كانت كذلك → الناس ينفقون أكثر → قد يغذي التضخم\n\n"
                "💡 <b>مفارقة شائعة:</b>\n"
                "البطالة المنخفضة جداً قد ترفع التضخم\n"
                "(أصحاب العمل يدفعون أكثر لجذب العمال → الأسعار ترتفع)\n"
                "→ الفيد يرفع الفائدة لتبريد الأمور."
            ),
        },
    },
    {
        "id": 15,
        "emoji": "🎓",
        "topic": {
            "fr": "Mettre tout ensemble — Ta première stratégie fondamentale",
            "en": "Putting it all together — Your first fundamental strategy",
            "es": "Uniendo todo — Tu primera estrategia fundamental",
            "ar": "تجميع كل شيء — استراتيجيتك الأساسية الأولى",
        },
        "content": {
            "fr": (
                "🏆 <b>Félicitations ! Tu as terminé le parcours fondamental.</b>\n\n"
                "Voici comment construire un biais fondamental simple :\n\n"
                "<b>Step 1 — Regarde le DXY</b>\n"
                "Montant → contexte haussier USD · Descendant → baissier USD\n\n"
                "<b>Step 2 — Check le calendrier (/day)</b>\n"
                "Y a-t-il des événements rouges aujourd'hui ?\n"
                "Si oui → attends la publication ou ferme tes positions avant\n\n"
                "<b>Step 3 — Lis la surprise</b>\n"
                "Résultat > prévision = surprise haussière pour la devise\n"
                "Résultat < prévision = surprise baissière\n\n"
                "<b>Step 4 — Identifie le régime</b>\n"
                "Risk-On ou Risk-Off ? L'or monte ? Le JPY monte ?\n\n"
                "<b>Step 5 — Combine avec le technique</b>\n"
                "Utilise /analyze pour avoir la confluence complète 🎯\n\n"
                "💡 <b>Souviens-toi :</b>\n"
                "La fondamentale donne le <b>POURQUOI</b>.\n"
                "La technique donne le <b>OÙ et QUAND</b> entrer.\n"
                "Les deux ensemble = trading professionnel. 🚀"
            ),
            "en": (
                "🏆 <b>Congratulations! You've completed the fundamental course.</b>\n\n"
                "Here's how to build a simple fundamental bias:\n\n"
                "<b>Step 1 — Check the DXY</b>\n"
                "Rising → bullish USD context · Falling → bearish USD\n\n"
                "<b>Step 2 — Check the calendar (/day)</b>\n"
                "Are there any red events today?\n"
                "If yes → wait for the release or close your positions before\n\n"
                "<b>Step 3 — Read the surprise</b>\n"
                "Actual > forecast = bullish surprise for the currency\n"
                "Actual < forecast = bearish surprise\n\n"
                "<b>Step 4 — Identify the regime</b>\n"
                "Risk-On or Risk-Off? Is gold rising? Is JPY rising?\n\n"
                "<b>Step 5 — Combine with technicals</b>\n"
                "Use /analyze for full confluence 🎯\n\n"
                "💡 <b>Remember:</b>\n"
                "Fundamentals give you the <b>WHY</b>.\n"
                "Technicals give you the <b>WHERE and WHEN</b> to enter.\n"
                "Both together = professional trading. 🚀"
            ),
            "es": (
                "🏆 <b>¡Felicidades! Has completado el curso fundamental.</b>\n\n"
                "Cómo construir un sesgo fundamental simple:\n\n"
                "<b>Paso 1 — Mira el DXY</b>\n"
                "Subiendo → contexto alcista USD · Bajando → bajista USD\n\n"
                "<b>Paso 2 — Revisa el calendario (/day)</b>\n"
                "¿Hay eventos rojos hoy?\n"
                "Si los hay → espera la publicación o cierra posiciones antes\n\n"
                "<b>Paso 3 — Lee la sorpresa</b>\n"
                "Real > previsión = sorpresa alcista para la divisa\n"
                "Real < previsión = sorpresa bajista\n\n"
                "<b>Paso 4 — Identifica el régimen</b>\n"
                "¿Risk-On o Risk-Off? ¿Sube el oro? ¿Sube el JPY?\n\n"
                "<b>Paso 5 — Combina con el técnico</b>\n"
                "Usa /analyze para confluencia completa 🎯\n\n"
                "💡 <b>Recuerda:</b>\n"
                "Los fundamentales dan el <b>PORQUÉ</b>.\n"
                "El análisis técnico da el <b>DÓNDE y CUÁNDO</b> entrar.\n"
                "Ambos juntos = trading profesional. 🚀"
            ),
            "ar": (
                "🏆 <b>تهانينا! لقد أكملت الدورة الأساسية.</b>\n\n"
                "إليك كيفية بناء تحيز أساسي بسيط:\n\n"
                "<b>الخطوة 1 — تحقق من DXY</b>\n"
                "صاعد → سياق صعودي للدولار · هابط → هبوطي للدولار\n\n"
                "<b>الخطوة 2 — تحقق من التقويم (/day)</b>\n"
                "هل هناك أحداث حمراء اليوم؟\n"
                "إذا كان نعم → انتظر الإصدار أو أغلق مراكزك قبله\n\n"
                "<b>الخطوة 3 — اقرأ المفاجأة</b>\n"
                "الفعلي > التوقع = مفاجأة صعودية للعملة\n"
                "الفعلي < التوقع = مفاجأة هبوطية\n\n"
                "<b>الخطوة 4 — حدد النظام</b>\n"
                "Risk-On أم Risk-Off؟ هل الذهب يرتفع؟ هل الين يرتفع؟\n\n"
                "<b>الخطوة 5 — ادمج مع التحليل التقني</b>\n"
                "استخدم /analyze للتقاطع الكامل 🎯\n\n"
                "💡 <b>تذكر:</b>\n"
                "التحليل الأساسي يعطيك <b>الـ لماذا</b>.\n"
                "التحليل التقني يعطيك <b>الـ أين والـ متى</b> للدخول.\n"
                "كلاهما معاً = تداول احترافي. 🚀"
            ),
        },
    },
]

TOTAL_LESSONS = len(LESSONS)
_LESSON_BY_ID = {l["id"]: l for l in LESSONS}


# ── UI strings ─────────────────────────────────────────────────────────────────

_UI = {
    "header": {
        "fr": "📚 <b>FONDAMENTALE — Leçon {n}/{total}</b>",
        "en": "📚 <b>FUNDAMENTALS — Lesson {n}/{total}</b>",
        "es": "📚 <b>FUNDAMENTOS — Lección {n}/{total}</b>",
        "ar": "📚 <b>الأساسيات — الدرس {n}/{total}</b>",
    },
    "progress_bar": {
        "fr": "Progression : {bar} {pct}%",
        "en": "Progress: {bar} {pct}%",
        "es": "Progreso: {bar} {pct}%",
        "ar": "التقدم: {bar} {pct}%",
    },
    "next_hint": {
        "fr": "➡️ <i>Tape /learn pour la prochaine leçon</i>",
        "en": "➡️ <i>Type /learn for the next lesson</i>",
        "es": "➡️ <i>Escribe /learn para la siguiente lección</i>",
        "ar": "➡️ <i>اكتب /learn للدرس التالي</i>",
    },
    "completed": {
        "fr": (
            "🏆 <b>Parcours terminé !</b>\n\n"
            "Tu as complété les <b>{total} leçons</b> d'analyse fondamentale.\n"
            "Tu es prêt(e) à combiner fondamentale + technique !\n\n"
            "🔁 Tape <code>/learn reset</code> pour recommencer depuis le début."
        ),
        "en": (
            "🏆 <b>Course completed!</b>\n\n"
            "You've completed all <b>{total} lessons</b> of fundamental analysis.\n"
            "You're ready to combine fundamentals + technicals!\n\n"
            "🔁 Type <code>/learn reset</code> to start over from the beginning."
        ),
        "es": (
            "🏆 <b>¡Curso completado!</b>\n\n"
            "Has completado las <b>{total} lecciones</b> de análisis fundamental.\n"
            "¡Estás listo/a para combinar fundamentales + técnico!\n\n"
            "🔁 Escribe <code>/learn reset</code> para empezar de nuevo."
        ),
        "ar": (
            "🏆 <b>اكتملت الدورة!</b>\n\n"
            "لقد أكملت جميع <b>{total} دروس</b> التحليل الأساسي.\n"
            "أنت مستعد لدمج الأساسيات مع التحليل التقني!\n\n"
            "🔁 اكتب <code>/learn reset</code> للبدء من جديد."
        ),
    },
    "reset_done": {
        "fr": "🔄 Progression réinitialisée ! Tape /learn pour recommencer.",
        "en": "🔄 Progress reset! Type /learn to start over.",
        "es": "🔄 ¡Progreso reiniciado! Escribe /learn para empezar.",
        "ar": "🔄 تم إعادة ضبط التقدم! اكتب /learn للبدء من جديد.",
    },
    "no_sub": {
        "fr": (
            "🔒 <b>Accès restreint</b>\n\n"
            "Cette commande nécessite un abonnement actif.\n"
            "Contactez l'administrateur pour obtenir l'accès."
        ),
        "en": (
            "🔒 <b>Access restricted</b>\n\n"
            "This command requires an active subscription.\n"
            "Contact the administrator to get access."
        ),
        "es": (
            "🔒 <b>Acceso restringido</b>\n\n"
            "Este comando requiere una suscripción activa.\n"
            "Contacta al administrador para obtener acceso."
        ),
        "ar": (
            "🔒 <b>الوصول مقيد</b>\n\n"
            "هذا الأمر يتطلب اشتراكاً نشطاً.\n"
            "تواصل مع المسؤول للحصول على الوصول."
        ),
    },
}


def _ui(key: str, lang: str, **kwargs) -> str:
    lang = lang if lang in ("fr", "en", "es", "ar") else "fr"
    text = _UI[key].get(lang, _UI[key].get("fr", key))
    return text.format(**kwargs) if kwargs else text


def _progress_bar(done: int, total: int, width: int = 10) -> str:
    filled = int(done / total * width)
    return "█" * filled + "░" * (width - filled)


# ── Handler ────────────────────────────────────────────────────────────────────

async def cmd_learn(update, context):
    """Handler /learn [reset]"""
    user_id = update.effective_user.id

    if not subscription_manager.is_user_active(user_id):
        await update.message.reply_text(_ui("no_sub", "fr"), parse_mode="HTML")
        return

    # Detect language from bot's language system
    from bot import get_lang
    lang = get_lang(str(update.effective_chat.id))
    if lang not in ("fr", "en", "es", "ar"):
        lang = "fr"

    # Handle /learn reset
    args = context.args or []
    if args and args[0].lower() == "reset":
        _reset_progress(user_id)
        await update.message.reply_text(_ui("reset_done", lang), parse_mode="HTML")
        return

    done_ids = _get_done(user_id)
    all_ids = [l["id"] for l in LESSONS]
    remaining = [lid for lid in all_ids if lid not in done_ids]

    if not remaining:
        await update.message.reply_text(
            _ui("completed", lang, total=TOTAL_LESSONS),
            parse_mode="HTML",
        )
        return

    lesson_id = remaining[0]
    lesson = _LESSON_BY_ID[lesson_id]
    lesson_num = all_ids.index(lesson_id) + 1

    _mark_done(user_id, lesson_id)

    done_count = len(done_ids) + 1
    pct = int(done_count / TOTAL_LESSONS * 100)
    bar = _progress_bar(done_count, TOTAL_LESSONS)

    header = _ui("header", lang, n=lesson_num, total=TOTAL_LESSONS)
    progress = _ui("progress_bar", lang, bar=bar, pct=pct)
    topic = lesson["topic"].get(lang, lesson["topic"]["fr"])
    content = lesson["content"].get(lang, lesson["content"]["fr"])
    next_hint = _ui("next_hint", lang)

    msg = (
        f"{header}\n"
        f"{progress}\n\n"
        f"{lesson['emoji']} <b>{_esc(topic)}</b>\n"
        f"{'─' * 30}\n\n"
        f"{content}\n\n"
        f"{'─' * 30}\n"
        f"{next_hint}"
    )

    await update.message.reply_text(msg, parse_mode="HTML")
