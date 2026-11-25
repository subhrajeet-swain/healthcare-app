import { type ReactNode, createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

export type Lang = "en" | "hi";
export type Pair = { en: string; hi: string };

// Hindi lines are machine-drafted; a native speaker must review them before real users.
export const STRINGS = {
  // shell
  signOut: { en: "Sign out", hi: "साइन आउट" },
  allReports: { en: "All reports", hi: "सभी रिपोर्ट" },
  loading: { en: "Loading…", hi: "लोड हो रहा है…" },
  tryAgain: { en: "Try again", hi: "फिर कोशिश करें" },
  problem: { en: "Problem", hi: "समस्या" },
  signedOut: { en: "You're signed out", hi: "आप साइन आउट हैं" },
  signIn: { en: "Sign in", hi: "साइन इन" },
  openLink: { en: "Open the sign-in link your lab sent you by SMS or WhatsApp.", hi: "आपकी लैब ने SMS या WhatsApp पर जो साइन-इन लिंक भेजा है, उसे खोलें।" },
  language: { en: "Language", hi: "भाषा" },
  greeting: { en: "Namaste", hi: "नमस्ते" },

  // login
  ledePhone: { en: "Use the mobile number you gave your lab.", hi: "लैब को दिया मोबाइल नंबर डालें।" },
  ledeCode: { en: "Enter the 6-digit code we sent to your phone.", hi: "आपके फ़ोन पर भेजा गया 6 अंकों का कोड डालें।" },
  mobileNumber: { en: "Mobile number", hi: "मोबाइल नंबर" },
  phoneHint: { en: "10 digits. We send a 6-digit code to this number.", hi: "10 अंक। हम इस नंबर पर 6 अंकों का कोड भेजेंगे।" },
  sending: { en: "Sending…", hi: "भेजा जा रहा है…" },
  sendCode: { en: "Send code", hi: "कोड भेजें" },
  codeLabel: { en: "6-digit code", hi: "6 अंकों का कोड" },
  codeHint: { en: "Sent to the number ending {last4}. It works for 5 minutes.", hi: "{last4} पर ख़त्म होने वाले नंबर पर भेजा गया। यह 5 मिनट तक चलेगा।" },
  checking: { en: "Checking…", hi: "जांच हो रही है…" },
  verify: { en: "Verify and continue", hi: "पुष्टि करें और आगे बढ़ें" },
  changeNumber: { en: "Change number", hi: "नंबर बदलें" },
  needSixDigits: { en: "Enter all 6 digits of the code.", hi: "कोड के सभी 6 अंक डालें।" },

  // consent
  beforeStart: { en: "Before we start", hi: "शुरू करने से पहले" },
  consentLede: { en: "Read how we handle your health data. You can change your mind at any time.", hi: "पढ़ें कि हम आपका स्वास्थ्य डेटा कैसे संभालते हैं। आप कभी भी अपना फ़ैसला बदल सकते हैं।" },
  yourChoice: { en: "Your data, your choice", hi: "आपका डेटा, आपकी मर्ज़ी" },
  consent1: { en: "Your phone number and name are stored encrypted. Only your lab and its doctors can see your data.", hi: "आपका फ़ोन नंबर और नाम एन्क्रिप्ट करके रखा जाता है। आपका डेटा केवल आपकी लैब और उसके डॉक्टर देख सकते हैं।" },
  consent2: { en: "We explain your reports in plain language. A doctor decides anything about treatment.", hi: "हम आपकी रिपोर्ट आसान भाषा में समझाते हैं। इलाज से जुड़ा हर फ़ैसला डॉक्टर लेते हैं।" },
  consent3: { en: "You can download all your data, or delete it, from your home screen.", hi: "आप होम स्क्रीन से अपना सारा डेटा डाउनलोड या डिलीट कर सकते हैं।" },
  purpose: { en: "Purpose", hi: "उद्देश्य" },
  coreService: { en: "Core service", hi: "मुख्य सेवा" },
  version: { en: "Version", hi: "संस्करण" },
  saving: { en: "Saving…", hi: "सहेजा जा रहा है…" },
  agree: { en: "I agree", hi: "मैं सहमत हूँ" },
  notNow: { en: "Not now, sign out", hi: "अभी नहीं, साइन आउट करें" },

  // dashboards
  dashPatient: { en: "Your reports", hi: "आपकी रिपोर्ट" },
  dashStaff: { en: "Lab console", hi: "लैब कंसोल" },
  dashDoctor: { en: "Review queue", hi: "जांच सूची" },
  dashAdmin: { en: "Lab settings", hi: "लैब सेटिंग्स" },
  dashPlatform: { en: "Platform", hi: "प्लेटफ़ॉर्म" },
  emptyPatient: { en: "No reports yet. Upload one above, or your lab adds it. Each report appears here with a plain-language explanation and your next step.", hi: "अभी कोई रिपोर्ट नहीं है। ऊपर से अपलोड करें, या आपकी लैब जोड़ेगी। हर रिपोर्ट यहाँ आसान भाषा में समझाई जाएगी, साथ में आपका अगला कदम।" },
  emptyStaff: { en: "Report uploads arrive in a later release. Nothing to do here yet.", hi: "रिपोर्ट अपलोड अगले संस्करण में आएगा। अभी यहाँ कुछ करना नहीं है।" },
  emptyDoctor: { en: "Nothing to review. Red results and trend alerts will wait here for your sign-off.", hi: "जांचने के लिए कुछ नहीं है। लाल परिणाम और ट्रेंड अलर्ट यहाँ आपकी मंज़ूरी का इंतज़ार करेंगे।" },
  emptyAdmin: { en: "Lab settings arrive in a later release.", hi: "लैब सेटिंग्स अगले संस्करण में आएंगी।" },
  emptyPlatform: { en: "Platform tools arrive in a later release.", hi: "प्लेटफ़ॉर्म टूल अगले संस्करण में आएंगे।" },
  reports: { en: "Reports", hi: "रिपोर्ट" },
  loadingReports: { en: "Loading your reports…", hi: "आपकी रिपोर्ट लोड हो रही हैं…" },
  reportsFailed: { en: "We couldn't load your reports. Refresh the page to try again.", hi: "आपकी रिपोर्ट लोड नहीं हो सकीं। फिर से कोशिश करने के लिए पेज रीफ़्रेश करें।" },
  fromLab: { en: "from your lab", hi: "आपकी लैब से" },
  yourAccount: { en: "Your account", hi: "आपका खाता" },
  phone: { en: "Phone", hi: "फ़ोन" },
  consent: { en: "Consent", hi: "सहमति" },
  given: { en: "Given", hi: "दी गई" },
  notGiven: { en: "Not given", hi: "नहीं दी गई" },
  deleteQ: { en: "Delete everything?", hi: "सब कुछ डिलीट करें?" },
  deleteBody: { en: "Your account, reports, consents and sign-in are removed. This cannot be undone.", hi: "आपका खाता, रिपोर्ट, सहमति और साइन-इन हटा दिए जाएंगे। इसे वापस नहीं किया जा सकता।" },
  deleting: { en: "Deleting…", hi: "डिलीट हो रहा है…" },
  yesDelete: { en: "Yes, delete my data", hi: "हाँ, मेरा डेटा डिलीट करें" },
  keepData: { en: "Keep my data", hi: "मेरा डेटा रखें" },
  download: { en: "Download my data", hi: "मेरा डेटा डाउनलोड करें" },
  deleteData: { en: "Delete my data", hi: "मेरा डेटा डिलीट करें" },

  // upload
  addReport: { en: "Add a report", hi: "रिपोर्ट जोड़ें" },
  reportFile: { en: "Report file", hi: "रिपोर्ट फ़ाइल" },
  fileHint: { en: "PDF from your lab, or a clear photo of each page. Up to 10 MB.", hi: "लैब की PDF, या हर पेज की साफ़ फ़ोटो। 10 MB तक।" },
  chooseFirst: { en: "Choose your report file first.", hi: "पहले अपनी रिपोर्ट फ़ाइल चुनें।" },
  uploading: { en: "Uploading…", hi: "अपलोड हो रहा है…" },
  upload: { en: "Upload report", hi: "रिपोर्ट अपलोड करें" },

  // report
  yourReport: { en: "Your report", hi: "आपकी रिपोर्ट" },
  collected: { en: "Collected {date}", hi: "{date} को सैंपल लिया गया" },
  added: { en: "Added {date}", hi: "{date} को जोड़ी गई" },
  notFound: { en: "Report not found", hi: "रिपोर्ट नहीं मिली" },
  notFoundBody: { en: "It may have been deleted, or the link belongs to another account.", hi: "शायद यह डिलीट हो गई है, या लिंक किसी और खाते का है।" },
  reportFailed: { en: "We couldn't load this report. Check your connection.", hi: "यह रिपोर्ट लोड नहीं हो सकी। अपना इंटरनेट कनेक्शन जांचें।" },
  progress: { en: "Progress", hi: "प्रगति" },
  progressLabel: { en: "Report progress", hi: "रिपोर्ट की प्रगति" },
  uploadAgain: { en: "Upload again", hi: "फिर से अपलोड करें" },
  whatItSays: { en: "What it says", hi: "इसमें क्या है" },
  results: { en: "Results", hi: "परिणाम" },
  viewOriginal: { en: "View original", hi: "मूल रिपोर्ट देखें" },
  normalRange: { en: "Normal range {range}", hi: "सामान्य सीमा {range}" },
  below: { en: "below {n}", hi: "{n} से कम" },
  above: { en: "above {n}", hi: "{n} से अधिक" },
  notPrinted: { en: "not printed", hi: "छपी नहीं है" },
  doctorTold: { en: "Your lab's doctor will be told and will look at this report.", hi: "आपकी लैब के डॉक्टर को बताया जाएगा और वे यह रिपोर्ट देखेंगे।" },
  next: { en: "Next", hi: "अगला कदम" },
  stepDone: { en: "Done", hi: "पूरा" },
  stepNow: { en: "Now", hi: "अभी" },
  stepLater: { en: "Later", hi: "बाद में" },
  stepStopped: { en: "Stopped", hi: "रुका" },
  progressLede: { en: "This usually takes under a minute. The page updates by itself.", hi: "इसमें आमतौर पर एक मिनट से कम लगता है। यह पेज अपने-आप अपडेट होता है।" },

  // chat
  askTitle: { en: "Ask about this report", hi: "इस रिपोर्ट के बारे में पूछें" },
  askHint: { en: "Answers come only from this report. A doctor decides anything about treatment.", hi: "जवाब केवल इसी रिपोर्ट से आते हैं। इलाज का हर फ़ैसला डॉक्टर लेते हैं।" },
  you: { en: "You", hi: "आप" },
  assistant: { en: "Prime", hi: "प्राइम" },
  yourQuestion: { en: "Your question", hi: "आपका सवाल" },
  charsLeft: { en: "{n} characters left", hi: "{n} अक्षर बाकी" },
  asking: { en: "Asking…", hi: "पूछा जा रहा है…" },
  ask: { en: "Ask", hi: "पूछें" },
  noQuestions: { en: "For example: “What is my Hemoglobin?” or “Why is this high?”", hi: "उदाहरण: “मेरा Hemoglobin कितना है?” या “यह ज़्यादा क्यों है?”" },

  // lab console
  newOrder: { en: "New test order", hi: "नया टेस्ट ऑर्डर" },
  patientPhone: { en: "Patient's mobile number", hi: "मरीज़ का मोबाइल नंबर" },
  patientName: { en: "Patient's name (optional)", hi: "मरीज़ का नाम (वैकल्पिक)" },
  creating: { en: "Creating…", hi: "बनाया जा रहा है…" },
  createOrder: { en: "Create order", hi: "ऑर्डर बनाएं" },
  orderCreated: { en: "Order created. Sample collected.", hi: "ऑर्डर बन गया। सैंपल लिया गया।" },
  labReports: { en: "Reports in this lab", hi: "इस लैब की रिपोर्ट" },
  noLabReports: { en: "No reports yet. Create an order when you collect a sample.", hi: "अभी कोई रिपोर्ट नहीं। सैंपल लेने पर ऑर्डर बनाएं।" },
  markInLab: { en: "Mark in lab", hi: "लैब में भेजें" },
  uploadResult: { en: "Upload result", hi: "परिणाम अपलोड करें" },
} satisfies Record<string, Pair>;

export type Key = keyof typeof STRINGS;
export type T = (key: Key, vars?: Record<string, string | number>) => string;

export function translate(lang: Lang, key: Key, vars?: Record<string, string | number>): string {
  let s = STRINGS[key][lang];
  for (const [k, v] of Object.entries(vars ?? {})) s = s.replaceAll(`{${k}}`, String(v));
  return s;
}

const LANG_KEY = "ph:lang";

function saved(): Lang {
  try {
    return localStorage.getItem(LANG_KEY) === "hi" ? "hi" : "en";
  } catch {
    return "en";
  }
}

type Ctx = { lang: Lang; setLang: (l: Lang) => void; t: T };
const LangContext = createContext<Ctx | null>(null);

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(saved);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try {
      localStorage.setItem(LANG_KEY, l);
    } catch {
      /* storage blocked: the choice holds for this visit */
    }
  }, []);

  const value = useMemo<Ctx>(() => ({ lang, setLang, t: (k, v) => translate(lang, k, v) }), [lang, setLang]);
  return <LangContext.Provider value={value}>{children}</LangContext.Provider>;
}

export function useLang(): Ctx {
  const ctx = useContext(LangContext);
  if (!ctx) throw new Error("useLang outside LangProvider");
  return ctx;
}

/** The one language switch, in the band on every screen. */
export function LangToggle() {
  const { lang, setLang, t } = useLang();
  return (
    <div className="toggle toggle--band" role="group" aria-label={t("language")}>
      <button className="toggle__btn" lang="en" aria-pressed={lang === "en"} onClick={() => setLang("en")}>
        English
      </button>
      <button className="toggle__btn hi" lang="hi" aria-pressed={lang === "hi"} onClick={() => setLang("hi")}>
        हिंदी
      </button>
    </div>
  );
}
