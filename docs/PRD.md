# SMART REMOTE AI
## מסמך אפיון מוצר, חוויית משתמש ותוכנית פיתוח ל-Claude Code

**גרסה:** 1.0 · **תאריך:** 15.10.2026 · **סטטוס:** אפיון לפיתוח ובדיקות על מכשירים אמיתיים

> **הנחיית יסוד:** זהו פרויקט Web מלא (Frontend + Backend) עם עיצוב פרימיום. אין להשתמש ב-Raspberry Pi, ואין לגעת באתר או בשירותים קיימים. בשלב הפיתוח, ה-Backend ירוץ על מחשב רגיל המחובר לרשת הביתית. הממשק יהיה אתר רספונסיבי ו-PWA בעברית, RTL.

---

## 1. חזון המוצר

**Smart Remote AI** הוא שלט אוניברסלי בדפדפן, המאגד שליטה בממיר **HOT עם Android TV / שירות Android TV Remote תואם** ובטלוויזיית **LG webOS (ככל הנראה webOS 6)**. במקום שני שלטים, המשתמש יקבל ממשק אחד מרשים, עם פעולות מהירות, ערוצים מועדפים, פקודות קוליות בעברית, ואפשרות עתידית לפעולות חכמות בעזרת AI.

**תוצאה רצויה:** פותחים אתר בטלפון, רואים מיד סטטוס של שני המכשירים, שולטים בהם בלחיצה אחת, ומאוחר יותר אומרים: ״תעביר לערוץ 12 ותנמיך קצת״.

**מה כבר נבדק בפועל:** אפליקציית Google TV בטלפון מצליחה לשלוט בממיר HOT, והשלט הפיזי המקורי של HOT מצליח לעבור לערוצים דרך מקשי הספרות.

**מה עדיין לא אומת:** האם לקוח צד שלישי באמצעות Android TV Remote v2 מצליח לצמד את הממיר; האם הממיר מגיב לפקודות ספרות דרך רשת; דגם ה-LG וההתאמה המלאה של כל פקודה; האם הפעלה מרחוק של LG אפשרית. אין להציג אף אחת מיכולות אלו כמאומתת עד לבדיקת המכשיר.

## 2. מסגרת והגבלות

| נושא | החלטה |
|---|---|
| פלטפורמה | אתר Web מלא + PWA; לא APK, לא אפליקציית Android |
| פריסה ראשונית | מחשב Windows / Linux רגיל ברשת הביתית; **לא Raspberry Pi** |
| שפה וכיווניות | עברית מלאה, RTL, תמיכה תקינה במספרים ובשמות אנגליים |
| מכשירים | HOT Android TV / HOT Fiber 4K כפי שמזוהה בפועל + LG webOS |
| שלט רגיל | ניווט, חזור, בית, כפתורי מדיה, ערוצים, ווליום ו-Mute בהתאם ליכולת |
| ערוצים ישירים | ספרות 0–9; לבצע בדיקת תמיכה ולא להבטיח מראש |
| קול | זיהוי עברית בדפדפנים תומכים, עם חלופה להזנת טקסט |
| AI | ארכיטקטורה מוכנה; מודל חיצוני אופציונלי וניתן לביטול |
| אינטרנט / חשיפה | בשלב ראשון רשת ביתית בלבד. אין לפתוח פורטים לאינטרנט |
| מוצר ראוי לשימוש | אין כפתורי דמה: כל פעולה אמיתית, לא נתמכת או מוסברת ככזו |

**הערת תשתית קריטית:** אתר Web לבדו לא יכול לנהל את חיבורי TCP הנדרשים ל-Android TV Remote v2 מתוך דפדפן רגיל. לכן נדרש Backend מקומי שזמין ברשת של המכשירים. את האתר עצמו אפשר לארח לצד השרת או בנפרד, כל עוד התעבורה המאובטחת בין הלקוחות ל-Backend מוגדרת כראוי. מחשב ה-Backend צריך להיות פועל כדי שפעולות השלט יעבדו.

## 3. ארכיטקטורת הפתרון

```text
טלפון / טאבלט / מחשב
   |
   | HTTPS (PWA, React, Hebrew RTL)
   v
Frontend: React + TypeScript + Vite
   |
   | REST / WebSocket (authenticated)
   v
Backend: Python FastAPI  [מחשב מקומי בלבד]
   |                          |
   | Android TV Remote v2     | LG webOS SSAP/WebSocket
   v                          v
HOT set-top box             LG webOS TV
```

### 3.1 Frontend

- **React + TypeScript + Vite**.
- **Tailwind CSS** עם Design Tokens ותמיכה ב-RTL.
- **Framer Motion / Motion** לאנימציות מוגבלות ומדויקות; התאמה ל-`prefers-reduced-motion`.
- **Lucide** לאייקונים עם שפה אחידה.
- **TanStack Query** לניהול מצב השרת ובקשות, ו-Zustand או Context למצב ממשק מקומי.
- **vite-plugin-pwa** ל-Manifest, אייקון, מסך פתיחה ושמירת shell. מצב Offline מציג מסכים שמורים, *לא* מבטיח פעולות שלט.
- אפשר להחליף ספקי ספריות אם נדרש, אבל לתעד כל חריגה.

### 3.2 Backend

- **Python 3.11+**, **FastAPI**, **Uvicorn**, **Pydantic**.
- **androidtvremote2** – לקוח Python לפרוטוקול Android TV Remote v2, כולל צימוד עם קוד וקבלת מקשים. מקור: https://github.com/tronikos/androidtvremote2
- **aiowebostv** או **bscpylgtv** – לקוח Python ל-LG webOS, עם אישור ראשוני בטלוויזיה ושמירת client key. מקור: https://github.com/home-assistant-libs/aiowebostv וגם https://github.com/chros73/bscpylgtv
- גילוי אוטומטי ב-LAN באמצעות mDNS/Zeroconf/SSDP בהתאם לספריות, ותמיד אפשרות להזנת כתובת IP ידנית.
- שכבת **DeviceAdapter** לשני סוגי המכשירים, ממשק פקודות אחיד ומודל capability flags.
- אחסון תצורה ב-SQLite או קובץ ייעודי עם הרשאות מוגבלות; credentials לא בלוגים ולא בדפדפן.
- תור פקודות סידרתי לכל מכשיר למניעת ערבוב פקודות, timeout, retry זהיר וחיווי שגיאה אנושי.

### 3.3 מגבלות אבטחה ורשת

- CORS מוגבל לכתובות האתר בלבד; להימנע מ-`*` עם הרשאות.
- אימות ל-Backend באמצעות סיסמה/Session או token אישי מוגן; אין להשאיר API פתוח לכל מי שברשת.
- השרת לא יפעל על 0.0.0.0 כברירת מחדל ללא צעד הגדרה מודע ואמצעי הגנה.
- יוגדר allowlist לכתובות של מכשירי LAN מזוהים, ללא Proxy כללי לכתובות שרירותיות.
- HTTPS נדרש לגישה מהטלפון במרבית תרחישי PWA/מיקרופון. `http://localhost` נחשב secure context במחשב המארח בלבד, **לא** כאשר גולשים מטלפון לכתובת HTTP של המחשב.
- אין גישה מרחוק מחוץ לבית ב-MVP; בעתיד ניתן להוסיף VPN / פתרון מאובטח אחר בנפרד.

## 4. שפה חזותית — Premium Dark Experience

**שאיפה:** מוצר שנראה כמו אפליקציית שלט יוקרתית של 2026, לא טופס טכני. מינימליסטי, חכם ומרשים — תוך שמירה על נוחות תפעול ביד אחת.

### 4.1 עקרונות

- **Dark-first:** רקע כחול־שחור עמוק עם Gradient כהה. בלי שחור מוחלט בכל המסך.
- **Glassmorphism עדין:** כרטיסיות שקופות למחצה עם גבול דק, blur מדוד וצל רך. קריאות קודמת לאפקט.
- **Aurora light:** הילות עמומות של טורקיז/סגול סביב אזורי מפתח; אין להשתמש באנימציות כבדות בכל המסך.
- **כפתורי שלט פיזיים־דיגיטליים:** עומק עדין, Press feedback, הילה קצרה בלחיצה, Haptics בדפדפנים תומכים ורק לאחר פעולה מפורשת.
- **Typography:** Heebo או Assistant לעברית, למשל עם גופן חלופי מערכת; מספרי ערוצים גדולים וברורים.
- **RTL Native:** זרימת מסך, Breadcrumbs, Icons כיווניים, טפסים; מספרי ערוצים ולוגים טכניים LTR כאשר צריך.
- **מצב גישה:** Contrast מספק, אזורי לחיצה מינימום 44×44px, מקשים מרכזיים 56–72px, תמיכה במקלדת וקורא מסך.

### 4.2 Design Tokens — ערכי פתיחה לעיצוב

| Token | ערך מוצע | שימוש |
|---|---|---|
| `--bg` | `#080B16` | רקע ראשי |
| `--surface` | `#11182B` | כרטיסיות |
| `--surface-glass` | `rgba(24,35,59,.68)` | זכוכית |
| `--accent` | `#6C6BFF` | סגול־אינדיגו |
| `--secondary` | `#22D3C5` | טורקיז |
| `--text` | `#F4F7FF` | טקסט |
| `--muted` | `#A6B3CB` | טקסט משני |
| `--danger` | `#FF667A` | שגיאה / כיבוי |
| `--radius-xl` | `24px` | כרטיסיות מובילות |

הערכים הם המלצה עיצובית ואינם עובדות על המכשירים. על Claude לבחור התאמות לפי קריאות, ניגודיות ונראות בפועל.

### 4.3 התנהגות רספונסיבית

- **Mobile 360–480px:** רוב השימוש, כרטיסי מכשירים, שלט גדול, ניווט תחתון קבוע, safe-area לאייפון, מקשי ספרות ובקרת עוצמה.
- **Tablet 600–1024px:** כרטיסי שליטה זה לצד זה; מקשים וצ'יפים גדולים.
- **Desktop 1024px+:** Sidebar ימני, אזור מרכזי לשלט ותצוגת פעילות/יכולות משמאל.
- אין גלילה אופקית; אין מקשים מכוסים על ידי bottom bar; בדיקות גם ב-landscape.

## 5. מסכי המוצר

### 5.1 מסך בית / Dashboard

- Header עם לוגו ״SMART REMOTE״, שם חלל (״סלון״), אייקון הגדרות וחיווי LAN.
- כרטיס HOT: מחובר/מנותק, שם מכשיר, כפתור ״פתח שלט״, מצב ערוץ אם נגיש בפועל בלבד.
- כרטיס LG: מחוברת/מנותקת, עוצמת קול וכניסת HDMI אם נגישות.
- פעולות מהירות: ״ערוץ קודם״, ״השתק״, ״בית״, ״HDMI״ — רק אם נתמכות.
- פס פעולות קוליות מעוצב עם שדה ״מה תרצה לראות?״ וכפתור מיקרופון.
- מצב חדש: הדגמה/Mock Mode שמסומן בבירור, מאפשר לבחון את העיצוב ללא מכשירים.

### 5.2 מסך שלט HOT

- מקש Power/Standby (אם נבדק), Home, Back, Menu/Guide אם נתמכים.
- D-Pad עגול, מרכז OK, אנימציית משוב בלחיצה.
- Volume ±, Mute, Channel ±; להבהיר איזה מכשיר אחראי לעוצמת הקול.
- Keypad 0–9 עם ספרות גדולות, כפתור מחיקה, ״שלח״ אופציונלי.
- Favorites: אריחי ערוצים הניתנים לעריכה במספר ושם, ללא רשימת מספרי ערוצים מומצאת.
- Play/Pause, Rewind, Forward לפי capability.
- חיווי ברור לפקודה שנשלחה מול הצלחה שנצפתה: ״נשלחה״ ≠ ״הערוץ השתנה״.

### 5.3 מסך שלט LG

- ווליום, Mute, Power Off, Input Source/HDMI, Home/Back, פתיחת אפליקציות מזוהות.
- אם יש תמיכה בעכבר/ניווט, להציג את הפקדים באופן מותנה.
- הפעלה ממצב כבוי באמצעות Wake-on-LAN רק אם התגלתה כתובת MAC והאפשרות נוסתה בפועל; אחרת ״לא זמין״ עם הסבר.
- אין להשתמש ב-CEC כהנחת בסיס.

### 5.4 מסך קול / AI

- מרכז המסך כפתור מיקרופון גדול עם waveform רך.
- טקסט זיהוי בזמן אמת, היסטוריית בקשות קצרה ואישור על פעולה.
- פקודות לדוגמה: ״ערוץ 12״, ״תגביר״, ״פתח יוטיוב״, ״תעבור ל-HDMI 2״.
- אם SpeechRecognition אינו זמין — שדה טקסט עם אותה חוויית משתמש.
- **אין מצב always listening ב-MVP.** רק לחיצה מפורשת להקלטה והרשאה נדרשת.
- פעולות מרובות: פירוק ל-Sequence, הצגת preview, והימנעות מביצוע חלקי שגוי ללא הודעה.

### 5.5 מכשירים והגדרות

- Scan for devices, הזנת IP ידנית, Pair, Re-pair, Disconnect.
- בחירת יעד ברירת מחדל לווליום: LG/HOT; בהתאם לבדיקה.
- בדיקת פקודות ספרתיות מובנית: ״שלח 1״, ״שלח 2״, ״שלח OK״; הצג תוצאות באופן מפורש.
- הגדרות שהייה בין ספרות, ״ENTER לאחר מספר״ ואפשרות שמירה לכל מכשיר.
- מסך Diagnostics: מזהה מכשיר לא רגיש, מצב חיבור, חיווי Last command, סוג שגיאה, export logs מסוננים ללא סודות.

## 6. מודל פקודות ויכולות

**רעיון מרכזי:** UI אינו שולח מחרוזות חופשיות ישירות למכשירים. הוא שולח פעולה מובנית ל-Backend, המאמת אותה ומעביר למתאם המתאים.

```json
{
  "target": "hot-living-room",
  "action": "key_press",
  "params": {"key": "DPAD_CENTER"},
  "request_id": "example-123"
}
```

**פקודות MVP**

| תחום | פעולות |
|---|---|
| HOT Navigation | `DPAD_UP/DOWN/LEFT/RIGHT`, `DPAD_CENTER`, `BACK`, `HOME` |
| HOT Media | `MEDIA_PLAY_PAUSE`, `MEDIA_REWIND`, `MEDIA_FAST_FORWARD` (לאחר בדיקת תמיכה) |
| HOT Numbers | `KEYCODE_0` … `KEYCODE_9`, עם תור ושיהוי ניתן לכוונון |
| HOT Channels | `CHANNEL_UP`, `CHANNEL_DOWN`, `LAST_CHANNEL` ככל שנתמך |
| LG Volume | `volume_up/down`, `mute`, `set_volume` אם זמין |
| LG Navigation | `home`, `back`, `up/down/left/right`, `ok` אם זמין |
| LG Inputs | `list_inputs`, `set_input` לבחירה מרשימה מזוהה |
| Power | `power_off`; `power_on` רק אם WOL נבדק ועובד |

**בדיקת ערוצים ישירים היא תנאי לקבלת הפיצ'ר:** ננסה `KEYCODE_1` ואז `KEYCODE_2`, עם זמן בין מקשים הניתן לשינוי, ונבדוק על הטלוויזיה אם עבר לערוץ 12. לפי הצורך ננסה `DPAD_CENTER` / `ENTER` לאחר ספרות, ללא הבטחה שהממיר יקבל זאת. השלט המקורי של HOT תומך בספרות, אך הוא עשוי להשתמש בפרוטוקול שונה מהשלט הרשתִי. אם לא עובד, לשמור על ניווט ו-Channel ± ולסמן Direct Channel Unsupported; לא לזייף הצלחה.

## 7. Pairing, Discovery ו-Reconnect

### 7.1 HOT

1. גילוי מ-LAN או הזנת כתובת IPv4 ידנית.
2. יצירת certificate/key בצד השרת כפי שמחייבת ספריית `androidtvremote2`.
3. פתיחת תהליך צימוד והצגת קוד שמופיע בממיר.
4. הזנת הקוד באתר, שמירת הקבצים בצד השרת בלבד, והתחברות.
5. חיווי דופק/מצב, reconnect עם backoff, כפתור ״צמד מחדש״.
6. אם לא ניתן לצמד צד שלישי, להציג שגיאה מדויקת ולתעד שלבי בדיקה; לא להפעיל ADB אוטומטית.

### 7.2 LG webOS

1. גילוי או הקלדת IP.
2. ניסיון חיבור SSAP באמצעות ספרייה קיימת.
3. בקשת צימוד מאושרת על מסך הטלוויזיה (היא חייבת להיות פעילה בזמן צימוד).
4. שמירת `client_key` בשרת, והצגת סטטוס מכשיר.
5. להציג רק יכולות המותרות והנתמכות ב-LG בפועל.

## 8. פקודות קוליות ו-AI

### 8.1 שכבת פקודות מקומית — בלי מודל AI

- שימוש ב-Web Speech API, `lang = 'he-IL'` אם הדפדפן תומך.
- ניתוח דטרמיניסטי לפקודות מוגדרות: ״ערוץ [מספר]״, ״הגבר/הנמך״, ״השתק״, ״פתח יוטיוב״, ״החלף ל-HDMI [מספר]״.
- יש להפריד בין speech-to-text לבין intent-to-command.
- להראות למשתמש את הטקסט שהתקבל לפני פעולה דו־משמעית.
- בחלק מהדפדפנים הזיהוי נשען על שירות ענן של הדפדפן; להציג הודעת פרטיות ולא לטעון שכל הדיבור מעובד מקומית.

### 8.2 שכבת AI אופציונלית

- Interface בשם `IntentProvider` עם `RuleBasedIntentProvider` כברירת מחדל, ו-`LLMIntentProvider` רק לאחר הגדרת API key בצד השרת.
- מודל שפה מחזיר JSON בעל schema קשיח: יעד, פעולה, פרמטרים ורמת ביטחון; השרת מאמת whitelist ולא מריץ shell או כתובות חופשיות.
- פעולה מורכבת לדוגמה: ״שים ערוץ 12 ואז תנמיך את הטלוויזיה״ → שתי פעולות מסודרות.
- ״מצא לי סרט מצחיק״ דורש מקור חיפוש וזמינות/קטלוג חיצוני; אם אין מקור, האפליקציה מציעה לפתוח אפליקציית סטרימינג או חיפוש, ולא ממציאה תוצאות.
- ״מה משודר כרגע?״ דורש EPG אמין ועדכני; לדחות או להציע חיבור לספק מידע מאומת.
- פעולות מתוזמנות כגון ״כבה בעוד שעה״ יחייבו Scheduler בצד השרת, עם תצוגה, ביטול ועמידות לאתחול; לא לממש כ-`setTimeout` בדפדפן.
- פקודות בלתי הפיכות/מפתיעות דורשות אישור מתאים.

## 9. API מוצע

| Method | Endpoint | תפקיד |
|---|---|---|
| GET | `/api/health` | Healthcheck וגרסת שרת |
| GET | `/api/devices` | מכשירים, סטטוס ויכולות |
| POST | `/api/devices/discover` | סריקת LAN עם Timeout |
| POST | `/api/devices` | הוספת מכשיר לפי IP/סוג |
| POST | `/api/devices/{id}/pair/start` | תחילת צימוד |
| POST | `/api/devices/{id}/pair/confirm` | קוד צימוד HOT / אישור מתאים |
| POST | `/api/devices/{id}/commands` | פעולה מובנית ומאומתת |
| POST | `/api/intents/parse` | ניתוח פקודה קולית/טקסט |
| GET | `/api/capabilities` | רשימת capabilities אפשרית |
| WS | `/ws/status` | Events בזמן אמת, reconnect ו-state |

**הערות:** לבחור קודי שגיאה ברורים (`NOT_PAIRED`, `NOT_CONNECTED`, `UNSUPPORTED`, `TIMEOUT`, `DENIED`, `INVALID_COMMAND`). בקשות חוזרות מפעולה רגישה יזוהו באמצעות `request_id` כדי למנוע כפילות. סכמות Pydantic קשיחות והגבלת קצב על פקודות מרובות.

## 10. מבנה פרויקט מבוקש

```text
smart-remote-ai/
  README.md
  .env.example
  docs/
    ARCHITECTURE.md
    TEST_PLAN.md
    DEVICE_CAPABILITIES.md
  frontend/
    package.json
    src/
      app/
      components/
        remote/
        devices/
        ui/
      pages/
        Dashboard.tsx
        HotRemote.tsx
        LgRemote.tsx
        VoiceAssistant.tsx
        Settings.tsx
      hooks/
      services/api.ts
      styles/
      types/
    public/
  backend/
    pyproject.toml
    app/
      main.py
      api/
      adapters/
        base.py
        android_tv.py
        lg_webos.py
        mock.py
      services/
        pairing.py
        discovery.py
        commands.py
        intent_parser.py
      models/
      storage/
    tests/
  scripts/
    dev-windows.ps1
    dev-unix.sh
```

## 11. תוכנית פיתוח מדורגת

**שלב A — אתר מרשים ונגיש, ללא מכשירים:** Layout, Design System, mock mode עם נתונים מסומנים, כל המסכים, אנימציות, RTL, PWA, בדיקות Responsive. הכפתורים ב-Mock מפעילים מצב סימולציה מסומן, לא מציגים עצמם כשליטה אמיתית.

**שלב B — Backend ותשתית:** Auth בסיסי, routes, models, DeviceAdapter, פריסה על Windows רגיל, CORS נכון, capability management, healthchecks.

**שלב C — שליטה אמיתית ב-HOT:** Discovery, pairing, navigation, volume/channel keys לפי תמיכה, reconnect, logs. בדיקת Google TV כנקודת ייחוס בלבד.

**שלב D — שליטה אמיתית ב-LG:** צימוד על מסך הטלוויזיה, ווליום, השתק, כיבוי, מקור HDMI; הפעלה רק אם נבדקה.

**שלב E — מעבר ישיר לערוצים:** Keypad, queue, בדיקת KEYCODE_0..9, timeout/delays, favorites מותאמים, דיווח Unsupported במקרה הצורך.

**שלב F — קול בעברית:** זיהוי דפדפן, fallback, parser לכללי פקודה, feedback, privacy.

**שלב G — AI ותסריטים חכמים:** ספק LLM אופציונלי, כלים מורשים בלבד, schedule backend, EPG רק עם מקור מאומת.

יש להציג בסיום כל שלב הוראות הרצה, בדיקות, רשימת מגבלות ו-*מה צריך שאבדוק ידנית על המכשירים*.

## 12. Definition of Done — קריטריונים קשיחים

- האתר פועל ב-Windows ללא Raspberry Pi, עם README ומערך פקודות הפעלה ברור.
- מסך בית ושני שלטים עובדים ומותאמים לטלפון 360px ולדסקטופ.
- עברית ו-RTL מלאים: אין טקסט הפוך או כפתורים שנעלמים.
- הצימוד ל-HOT ול-LG נשמר ואינו נשבר באתחול השרת, ככל שהמכשירים מאפשרים זאת.
- פקודות navigation אמיתיות נשלחות ל-HOT; אם לא, יש error מפורש ולא Success פיקטיבי.
- כפתורי הספרות נבדקו בפועל, ומסך Diagnostics מתעד supported / unsupported / unknown.
- ווליום LG עובד רק כשהטלוויזיה צומדה והפעולה נתמכת.
- פרטי צימוד ו-API keys אינם נחשפים ל-Frontend או ללוגים.
- אין שימוש במפתחות API משובצים; `.env.example` מכיל placeholders בלבד.
- בדיקות Unit עבור parsers ו-adapters mock; Backend API integration tests; Frontend smoke tests / E2E לשימוש בסיסי.
- בזמן שאין מחשב Backend פעיל, האתר מסביר בבירור שאין חיבור ואינו מזייף פעולה.
- התמיכה בקול מסומנת כתלויה בדפדפן ובהרשאות, כולל חלופת הקלדה.

## 13. הפעלה מקומית — מה Claude חייב לספק

1. גרסאות נדרשות של Node.js/Python והוראות התקנה ב-Windows 11.
2. הוראות לפיתוח: Terminal A ל-Backend, Terminal B ל-Frontend; URL מדויק מקובצי הפרויקט שנוצרים.
3. הוראות ל-Production Build ושירות על מחשב רגיל, עם HTTPS מהטלפון כשיש צורך ב-PWA/מיקרופון.
4. Firewall rule מינימלי ומוסבר בלבד, ואיסור לחשוף פורטים ל-WAN.
5. Check-list לצימוד, Debugging והדגמת פקודות בשני מכשירים.
6. גישה נוחה למצב Demo גם בלי HOT/LG.

## 14. סיכונים ואי-ודאויות

| סיכון | מיתון |
|---|---|
| Google TV עובד אבל לקוח צד שלישי לא מצליח לצמד | בדיקה ישירה עם androidtvremote2, טיפול בשגיאות, תיעוד; לא להניח הצלחה |
| מספרים לא מפעילים ערוץ ב-HOT | capability test, config delays/ENTER, fallback ל-Channel ± |
| טלוויזיית LG כבויה אינה נגישה דרך WebSocket | תיוג Offline; WOL רק כאשר הוגדר ונבדק |
| PWA דרך HTTP בכתובת LAN לא מאפשר מיקרופון | HTTPS עם תעודה מהימנה / פתרון מקומי מאובטח |
| הקול לא נתמך בדפדפן מסוים | capability detection וחלופת טקסט |
| אתר פועל אך מחשב השרת כבוי | מצב Disconnected ברור, ללא הבטחת פעולות |
| אי-דיוק AI בערוצים/תכנים | schema, allowlist, קטלוג מועדפים מוגדר, ללא המצאת מידע |

## 15. מקורות טכניים לבדיקה והטמעה

1. Android TV Remote v2 Python: https://github.com/tronikos/androidtvremote2
2. Android TV Remote v2 demo and pairing flow: https://github.com/tronikos/androidtvremote2/blob/main/src/demo.py
3. Android TV remote key codes/protocol: https://github.com/tronikos/androidtvremote2/blob/main/src/androidtvremote2/remotemessage.proto
4. LG webOS Python library aiowebostv: https://github.com/home-assistant-libs/aiowebostv
5. LG webOS Python library bscpylgtv: https://github.com/chros73/bscpylgtv
6. MDN Web Speech API: https://developer.mozilla.org/en-US/docs/Web/API/Web_Speech_API
7. MDN SpeechRecognition compatibility: https://developer.mozilla.org/en-US/docs/Web/API/SpeechRecognition
8. MDN secure contexts: https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Secure_Contexts
9. MDN Service Workers: https://developer.mozilla.org/en-US/docs/Web/API/Service_Worker_API/Using_Service_Workers

המקורות מתעדים ספריות ויכולות כלליות. הם **אינם** ראיה לתמיכה המעשית בכל פקודה בדגם HOT/LG הספציפי. הצלחה תיבדק על החומרה האמיתית.

---

# 16. COPY-READY MASTER PROMPT FOR CLAUDE CODE

> הדבק את הפרומפט הבא ב-Claude Code יחד עם קובץ האפיון הזה (או הפנה אליו בתיקיית הפרויקט). בקש מ-Claude להתקדם שלב-שלב, אך לייצר קוד אמיתי ולא רק Mockups.

```text
You are a senior full-stack engineer, product designer, and QA lead.
Build a production-minded, PREMIUM-quality, Hebrew-first RTL web app named "Smart Remote AI" according to the attached PRD. Do not just make wireframes or a static landing page: implement a working frontend and local backend, maintainable adapter architecture, tests, docs, and a clear setup flow.

HARD CONSTRAINTS
- Web app only (React/TypeScript/PWA), NO native Android APK.
- NO Raspberry Pi, NO use of existing servers/websites/services. The local backend must initially run on a regular Windows PC and communicate with devices on the home LAN.
- The website should be a polished 2026 premium dark experience with restrained glassmorphism, aurora gradients, excellent tactile remote controls, fluid but performant microinteractions, accessible focus states, and responsive Hebrew RTL layouts.
- Treat the LG webOS version as unconfirmed; the user estimates webOS 6.
- The user's Google TV mobile remote successfully controls the HOT set-top box. The physical HOT remote can enter channel numbers. This does NOT guarantee a third-party Android TV Remote v2 client can pair or that KEYCODE_0..9 select channels via LAN.
- Do not invent support or return fake success. Distinguish discovery, connection, command sent, and device-observed result. Unknown capabilities must remain "unknown" until tested.
- Never require ADB, rooted devices, external IR hardware, or cloud subscriptions for core remote functions.
- Never expose pairing certificates, private keys, tokens, or AI API keys to the browser or logs.
- No WAN port forwarding or unauthenticated device-control API.

STACK
Frontend: React + TypeScript + Vite + Tailwind CSS + Lucide + Motion/Framer Motion + a sensible data/cache layer + Vite PWA plugin. Use CSS variables for a unified design system. RTL by default.
Backend: Python 3.11+, FastAPI, Pydantic, Uvicorn. AndroidTV adapter leveraging https://github.com/tronikos/androidtvremote2, LG adapter leveraging either https://github.com/home-assistant-libs/aiowebostv or https://github.com/chros73/bscpylgtv. Support auto-discovery and manual IP entry, pairing/re-pairing, reconnection, capability detection, and structured error reporting.

MUST-HAVE SCREENS
1. Dashboard with HOT + LG device cards, live connection states, clear quick actions.
2. HOT Remote with large D-pad/OK, home/back, channel+/-, volume/mute where supported, playback, 0–9 numeric keypad, configurable direct-channel behavior, favorites.
3. LG Remote with volume, mute, power-off, source/input select, navigation where supported. WOL power-on must be feature-gated and tested.
4. Voice & AI screen with microphone (SpeechRecognition he-IL where supported), typed-text fallback, speech transcript and command preview.
5. Settings/Devices: discovery, manual IP, pairing wizard, tests for individual numeric keys, diagnostics, connected device capabilities, clear errors.

BEHAVIOR
- Implement a real adapters interface and typed commands. Do not make uncontrolled magic key names.
- Numeric channel test: send KEYCODE_1, KEYCODE_2 sequentially with configurable delay; allow optional ENTER/DPAD_CENTER as an experiment. Never mark channel switching as verified until physically observed by user. Keep a per-device capability setting with UNKNOWN/SUPPORTED/UNSUPPORTED.
- Favor LG for TV volume by configurable preference; do not claim to know volume route without checking.
- For voice, start with deterministic Hebrew grammar ("ערוץ 12", "תגביר", "השתק", "פתח יוטיוב", "HDMI 2") that works without an AI key; add an optional LLM intent interface later. Never fabricate EPG/live programming or streaming catalog data.
- Schedule delayed actions server-side, not only in browser state.
- Backend must be accessible to the phone on the same LAN and have a credible HTTPS deployment guide for microphone and PWA support. localhost on the developer PC is not the same origin as a phone visiting the PC's LAN IP.
- Provide an explicit Demo Mode that simulates buttons while visually labeling it as a demo, separate from real connected states.

DELIVERY STEPS
A. Generate the actual repository skeleton, dependencies, and detailed README for Windows.
B. First implement finished design system, all responsive screens, accessible interactions, and a clearly labeled demo mode. Verify at 360px, 390px, tablet, and desktop widths.
C. Implement backend schemas, authentication, endpoints, state updates and mock adapters with tests.
D. Implement Android TV discovery, pairing, and navigation using upstream library APIs. Include diagnostics, safe cert storage, reconnection; provide a physical-device test checklist. Stop claiming functionality when hardware has not yet been tested.
E. Implement LG pairing and supported controls with explicit capability checks.
F. Implement numeric keypad testing and channel favorites.
G. Implement Hebrew voice commands with compatibility fallback.
H. Add OPTIONAL AI provider with a strict JSON schema/allowlist, no browser-side API keys, and user confirmation for unexpected commands.

ACCEPTANCE AND QUALITY
- Clean install/build/test on Windows documented and ideally scripted (PowerShell).
- Backend unit/API tests, parser tests, frontend checks; no critical console errors.
- Real error messages and loading states; fully working navigation and responsive layouts.
- Real paired-device operations only after successful hardware tests. No fake "success" toasts.
- Secure-by-default settings, local-only initial deployment, clear feature limitations.
- At the end of every delivery step, summarize exactly what was built, what was tested automatically, what still requires physical-device testing, and the next commands to run.

Start now by reading the PRD, proposing the final file tree and completing STEP A + STEP B with code. Do not ask non-essential questions. Build rather than merely describe.
```
