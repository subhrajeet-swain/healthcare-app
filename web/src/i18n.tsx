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
  openLink: { en: "Open the sign-in link your lab gave you.", hi: "आपकी लैब ने जो साइन-इन लिंक दिया है, उसे खोलें।" },
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
  progressSlow: { en: "Taking longer than usual. Your report is safe and will be read automatically.", hi: "सामान्य से ज़्यादा समय लग रहा है। आपकी रिपोर्ट सुरक्षित है और अपने-आप पढ़ी जाएगी।" },

  // red report banner, review pending, doctor's note
  urgentBanner: { en: "One or more results need attention today. Please call your lab or a doctor.", hi: "एक या ज़्यादा परिणामों पर आज ही ध्यान देना ज़रूरी है। कृपया अपनी लैब या किसी डॉक्टर को फ़ोन करें।" },
  reviewPending: { en: "A doctor is also checking this report. If they add a note, it will show here.", hi: "एक डॉक्टर यह रिपोर्ट भी जांच रहे हैं। वे कोई नोट जोड़ेंगे तो वह यहाँ दिखेगा।" },
  doctorNote: { en: "A note from your lab's doctor", hi: "आपकी लैब के डॉक्टर का नोट" },

  // share with a doctor (a link, no sign-in) and the page the doctor opens
  shareTitle: { en: "Share with a doctor", hi: "डॉक्टर के साथ साझा करें" },
  shareLede: { en: "Make a link your doctor can open without signing in. It shows this report's results and explanation, not the original file or your questions. You can stop sharing at any time.", hi: "ऐसा लिंक बनाएं जिसे आपके डॉक्टर साइन इन किए बिना खोल सकें। इसमें इस रिपोर्ट के परिणाम और व्याख्या दिखती है, मूल फ़ाइल या आपके सवाल नहीं। आप कभी भी साझा करना बंद कर सकते हैं।" },
  shareFor: { en: "The link works for", hi: "लिंक इतने समय तक चलेगा" },
  shareH1: { en: "1 hour", hi: "1 घंटा" },
  shareH24: { en: "24 hours", hi: "24 घंटे" },
  shareD7: { en: "7 days", hi: "7 दिन" },
  shareMake: { en: "Create link", hi: "लिंक बनाएं" },
  shareMaking: { en: "Creating…", hi: "बनाया जा रहा है…" },
  shareLink: { en: "Link to share", hi: "साझा करने का लिंक" },
  shareCopy: { en: "Copy link", hi: "लिंक कॉपी करें" },
  shareCopied: { en: "Link copied. Send it to your doctor.", hi: "लिंक कॉपी हो गया। इसे अपने डॉक्टर को भेजें।" },
  shareSelect: { en: "Select the link above and copy it.", hi: "ऊपर का लिंक चुनकर कॉपी करें।" },
  shareExpires: { en: "Expires {when}", hi: "{when} को समाप्त" },
  shareOpen: { en: "Links that are open", hi: "खुले हुए लिंक" },
  shareStop: { en: "Stop sharing", hi: "साझा करना बंद करें" },
  sharedTitle: { en: "A lab report shared with you", hi: "आपके साथ साझा की गई लैब रिपोर्ट" },
  sharedBy: { en: "Shared by the patient, expires {when}", hi: "मरीज़ ने साझा किया, {when} को समाप्त" },
  sharedGone: { en: "This link no longer works", hi: "यह लिंक अब काम नहीं करता" },
  sharedGoneBody: { en: "It has expired, or the patient stopped sharing it. Ask the patient for a new link.", hi: "यह समाप्त हो चुका है, या मरीज़ ने साझा करना बंद कर दिया है। मरीज़ से नया लिंक माँगें।" },
  sharedEmpty: { en: "None of the shared reports can be shown right now.", hi: "साझा की गई कोई भी रिपोर्ट अभी दिखाई नहीं जा सकती।" },

  // reports home summary
  latestReport: { en: "Latest report · {date}", hi: "ताज़ा रिपोर्ट · {date}" },
  testsOne: { en: "1 test", hi: "1 जांच" },
  testsMany: { en: "{n} tests", hi: "{n} जांचें" },
  statReports: { en: "reports", hi: "रिपोर्ट" },
  statTests: { en: "tests read", hi: "जांचें पढ़ी गईं" },
  statUrgent: { en: "urgent reports", hi: "तुरंत ध्यान वाली रिपोर्ट" },
  countGreen: { en: "{n} normal", hi: "{n} सामान्य" },
  countAmber: { en: "{n} outside range", hi: "{n} सीमा से बाहर" },
  countRed: { en: "{n} urgent", hi: "{n} तुरंत ध्यान" },
  back: { en: "Back to reports", hi: "रिपोर्ट पर वापस" },

  // bottom nav
  navLabel: { en: "Main", hi: "मुख्य" },
  navReports: { en: "Reports", hi: "रिपोर्ट" },
  navTrends: { en: "Trends", hi: "रुझान" },
  navChat: { en: "Chat", hi: "सवाल" },
  navProfile: { en: "Profile", hi: "प्रोफ़ाइल" },
  chatAbout: { en: "About your report from {date}.", hi: "{date} की आपकी रिपोर्ट के बारे में।" },
  openReport: { en: "Open the report", hi: "रिपोर्ट खोलें" },
  chatNone: { en: "You can ask questions once a report has been read. Upload one under Reports.", hi: "रिपोर्ट पढ़ ली जाने के बाद आप सवाल पूछ सकते हैं। रिपोर्ट में जाकर एक अपलोड करें।" },

  // trends: one chart per test
  trendsLede: { en: "How each result has moved across your reports.", hi: "आपकी रिपोर्ट में हर जांच कैसे बदली है।" },
  loadingTrends: { en: "Loading your trends…", hi: "आपके रुझान लोड हो रहे हैं…" },
  trendsFailed: { en: "We couldn't load your trends. Refresh the page to try again.", hi: "आपके रुझान लोड नहीं हो सके। फिर से कोशिश करने के लिए पेज रीफ़्रेश करें।" },
  trendsEmpty: { en: "Your charts appear here once a report has been read. Each test gets its own chart.", hi: "रिपोर्ट पढ़ी जाने के बाद आपके चार्ट यहाँ दिखेंगे। हर जांच का अपना चार्ट होगा।" },
  trendRising: { en: "Rising", hi: "बढ़ रहा है" },
  trendInReview: { en: "Under review", hi: "डॉक्टर देख रहे हैं" },
  trendFalling: { en: "Falling", hi: "घट रहा है" },
  chartSeries: { en: "Results over time", hi: "समय के साथ परिणाम" },
  excludedOne: { en: "One result (in {units}) can't be compared with the others, so it's left out.", hi: "एक परिणाम ({units} में) बाकी परिणामों से मिलाया नहीं जा सकता, इसलिए उसे छोड़ दिया गया है।" },
  excludedMany: { en: "{n} results (in {units}) can't be compared with the others, so they're left out.", hi: "{n} परिणाम ({units} में) बाकी परिणामों से मिलाए नहीं जा सकते, इसलिए उन्हें छोड़ दिया गया है।" },

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

  // doctor review queue
  docWaiting: { en: "{n} waiting", hi: "{n} इंतज़ार में" },
  docLoadFailed: { en: "We couldn't load this. Check your connection and try again.", hi: "यह लोड नहीं हो सका। अपना इंटरनेट कनेक्शन जांचें और फिर कोशिश करें।" },
  docNoName: { en: "Name not given", hi: "नाम नहीं दिया गया" },
  docRaised: { en: "Raised {date}", hi: "{date} को आई" },
  docNotFound: { en: "Review item not found", hi: "जांच की मद नहीं मिली" },
  docBack: { en: "Back to the queue", hi: "सूची पर वापस" },
  docAsked: { en: "Patient asked", hi: "मरीज़ ने पूछा" },
  docHeld: { en: "Reply held back", hi: "रोका गया जवाब" },
  docNoReport: { en: "No report is attached to this item.", hi: "इस मद के साथ कोई रिपोर्ट जुड़ी नहीं है।" },
  docDecide: { en: "Decision", hi: "फ़ैसला" },
  docHintReport: { en: "Approve releases the report as it is. Edit adds one fixed note. Escalate asks the patient to call the lab today.", hi: "मंज़ूर करने पर रिपोर्ट जैसी है वैसी मरीज़ तक पहुँचती है। बदलने पर एक तय नोट जुड़ता है। आगे भेजने पर मरीज़ से आज ही लैब को फ़ोन करने को कहा जाता है।" },
  docHintTrend: { en: "Your decision is recorded against this trend alert.", hi: "आपका फ़ैसला इस ट्रेंड अलर्ट के साथ दर्ज होगा।" },
  docHintChat: { en: "Approve keeps the reply as it is. Edit adds one fixed note to the chat.", hi: "मंज़ूर करने पर जवाब जैसा है वैसा रहता है। बदलने पर चैट में एक तय नोट जुड़ता है।" },
  docApprove: { en: "Approve", hi: "मंज़ूर करें" },
  docEdit: { en: "Edit", hi: "बदलें" },
  docEscalate: { en: "Escalate", hi: "आगे भेजें" },
  docPickNote: { en: "Pick one note", hi: "एक नोट चुनें" },
  docSend: { en: "Send note", hi: "नोट भेजें" },
  docApproved: { en: "Approved", hi: "मंज़ूर" },
  docEdited: { en: "Edited", hi: "बदला गया" },
  docEscalated: { en: "Escalated", hi: "आगे भेजा गया" },
  docDoneReport: { en: "The patient can now see this report.", hi: "मरीज़ अब यह रिपोर्ट देख सकता है।" },
  docDoneEscalated: { en: "The patient can now see this report, with a note to call the lab today.", hi: "मरीज़ अब यह रिपोर्ट देख सकता है, साथ में आज ही लैब को फ़ोन करने का नोट है।" },
  docDoneChat: { en: "Your note was added to the patient's chat.", hi: "आपका नोट मरीज़ की चैट में जोड़ दिया गया।" },
  docDoneOther: { en: "Your decision is recorded.", hi: "आपका फ़ैसला दर्ज हो गया।" },

  // family profiles
  famSwitch: { en: "Whose reports", hi: "किसकी रिपोर्ट" },
  famMe: { en: "Me", hi: "मैं" },
  famActingFor: { en: "Viewing reports of", hi: "इनकी रिपोर्ट देख रहे हैं" },
  famTitle: { en: "Family", hi: "परिवार" },
  famLede: { en: "Keep your family's reports here too. Switch between people at the top of the screen.", hi: "अपने परिवार की रिपोर्ट भी यहाँ रखें। स्क्रीन के ऊपर से व्यक्ति बदलें।" },
  famChild: { en: "Child", hi: "बच्चा" },
  famParent: { en: "Parent", hi: "माता-पिता" },
  famSpouse: { en: "Spouse", hi: "जीवनसाथी" },
  famOther: { en: "Other", hi: "अन्य" },
  famActive: { en: "Active", hi: "सक्रिय" },
  famWaiting: { en: "Waiting for them to accept", hi: "उनकी मंज़ूरी का इंतज़ार" },
  famAsks: { en: "Asks to manage your reports", hi: "आपकी रिपोर्ट संभालना चाहते हैं" },
  famManages: { en: "Can see and upload your reports", hi: "आपकी रिपोर्ट देख और अपलोड कर सकते हैं" },
  famAccept: { en: "Accept", hi: "मंज़ूर करें" },
  famDecline: { en: "Decline", hi: "मना करें" },
  famStop: { en: "Stop access", hi: "पहुँच बंद करें" },
  famRemove: { en: "Remove", hi: "हटाएं" },
  famYesRemove: { en: "Yes, remove", hi: "हाँ, हटाएं" },
  famKeep: { en: "Keep", hi: "रहने दें" },
  famRemoveChildWarn: { en: "Their reports are deleted too, unless someone else also manages them. This cannot be undone.", hi: "उनकी रिपोर्ट भी डिलीट हो जाएंगी, जब तक कोई और भी उन्हें नहीं संभालता। इसे वापस नहीं किया जा सकता।" },
  famAdd: { en: "Add someone", hi: "किसी को जोड़ें" },
  famWho: { en: "Who is it?", hi: "यह कौन है?" },
  famName: { en: "Their name", hi: "उनका नाम" },
  famChildConsent: { en: "A child has no phone or sign-in of their own. By adding them, you give consent for their reports, as their parent or guardian.", hi: "बच्चे का अपना फ़ोन या साइन-इन नहीं होता। उन्हें जोड़कर आप माता-पिता या अभिभावक के रूप में उनकी रिपोर्ट के लिए सहमति देते हैं।" },
  famInviteHint: { en: "They sign in with this number to accept and give their own consent.", hi: "वे इसी नंबर से साइन इन करके मंज़ूरी और अपनी सहमति देंगे।" },
  famAddChild: { en: "Add child", hi: "बच्चा जोड़ें" },
  famSendInvite: { en: "Send invite", hi: "न्योता भेजें" },
  famChildAdded: { en: "Added. Switch to them at the top of the screen.", hi: "जोड़ दिया गया। स्क्रीन के ऊपर से उन पर जाएं।" },
  famInvited: { en: "Invite sent. It shows as active once they accept.", hi: "न्योता भेज दिया गया। उनके मंज़ूर करने पर यह सक्रिय दिखेगा।" },
  // whatsapp
  waTitle: { en: "WhatsApp", hi: "व्हाट्सऐप" },
  waLede: { en: "Link your WhatsApp number to get a message when a report is ready, and to ask about it there.", hi: "अपना WhatsApp नंबर जोड़ें, ताकि रिपोर्ट तैयार होने पर संदेश मिले और आप वहीं उसके बारे में पूछ सकें।" },
  waUnavailable: { en: "Your lab hasn't set up WhatsApp yet.", hi: "आपकी लैब ने अभी WhatsApp शुरू नहीं किया है।" },
  waGetCode: { en: "Get a link code", hi: "लिंक कोड पाएं" },
  waCode: { en: "Your code", hi: "आपका कोड" },
  waSendCode: { en: "Send {text} to {number} on WhatsApp. The code works for {min} minutes.", hi: "WhatsApp पर {number} को {text} भेजें। यह कोड {min} मिनट तक चलेगा।" },
  waCopy: { en: "Copy", hi: "कॉपी करें" },
  waCopied: { en: "Copied.", hi: "कॉपी हो गया।" },
  waLinked: { en: "Linked to {number}.", hi: "{number} से जुड़ा है।" },
  waOptedOut: { en: "Messages are paused. Send START on WhatsApp to turn them back on.", hi: "संदेश रुके हुए हैं। दोबारा चालू करने के लिए WhatsApp पर START भेजें।" },
  waUnlink: { en: "Unlink", hi: "अनलिंक करें" },
  // telegram (Hindi machine-drafted)
  tgTitle: { en: "Telegram", hi: "टेलीग्राम" },
  tgLede: { en: "Connect Telegram to get a message when a report is ready, and to ask about it there.", hi: "टेलीग्राम जोड़ें, ताकि रिपोर्ट तैयार होने पर संदेश मिले और आप वहीं उसके बारे में पूछ सकें।" },
  tgUnavailable: { en: "Your lab hasn't set up Telegram yet.", hi: "आपकी लैब ने अभी टेलीग्राम शुरू नहीं किया है।" },
  tgConnect: { en: "Connect Telegram", hi: "टेलीग्राम जोड़ें" },
  tgLinked: { en: "Connected.", hi: "जुड़ा हुआ है।" },
  tgOptedOut: { en: "Messages are paused. Send /start on Telegram to turn them back on.", hi: "संदेश रुके हुए हैं। दोबारा चालू करने के लिए टेलीग्राम पर /start भेजें।" },
  tgUnlink: { en: "Unlink", hi: "अनलिंक करें" },
  viaTelegram: { en: "via Telegram", hi: "टेलीग्राम से" },
  callLab: { en: "Call your lab", hi: "अपनी लैब को फ़ोन करें" },
  viaWhatsApp: { en: "via WhatsApp", hi: "WhatsApp से" },
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
