"""Fact detectors shared by the fact-extractability and entity probes.

Every detector takes a list of Page objects (auditlib.context.Page, with .doc, .role, .final_url) and returns
either None or a Found dict: {"value": <=200 chars, "page": url, "source": "text|meta:<k>|jsonld:<Type>.<prop>|link:<kind>|form|heading"}.
Detectors read the served HTML only. They are deliberately broad on phrasing and narrow on structure, and
they never raise on odd input.
"""
import re
from urllib.parse import urlsplit

from .htmldoc import PRICE_RE

# ------------------------------------------------------------------ regexes
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
# Phone layouts. The first alternative is the Anglo shape (area code, exchange, number). The second is the
# international form with a country code and whatever grouping the country uses: France and Belgium pair the
# digits ("+33 1 42 72 00 00"), Australia and India lead with a one- or two-digit area code ("+61 2 9000 0000",
# "+91 11 2690 7400"). The Anglo shape could not read those because it wants two digits in the first group and
# three in the second, so a Paris bistro with its number in the footer was reported as having no phone. The
# third is the French domestic form: five pairs starting with 0. Callers still require 9 to 15 digits and either
# a leading "+" or a cue word, so a date or a reference number does not pass.
PHONE_TEXT_RE = re.compile(
    r"(?<![\w/])(?:(\+\d{1,3}[\s.\-]?)?(\(?\d{2,5}\)?[\s.\-]?)\d{3,4}[\s.\-]?\d{3,5}"
    r"|\+\d{1,3}(?:[\s.\-]\(?\d{1,5}\)?){2,5}"
    r"|0\d(?:[\s.]\d{2}){4})(?![\w/])")
# The cue word before a number, in the languages the address grammars cover: "Tél. :", "Telefon:", "Teléfono:".
PHONE_CUE_RE = re.compile(r"\b(phone|tel|t[eé]l|t[eé]l[eé]phone|tel[eé]fono|telefon|telefone|telefoon|call|mobile|cell|handy|whatsapp|fax|ph)\b\.?\s*:?\s*$", re.I)
SALES_LED_RE = re.compile(
    r"\b(request|book|schedule|arrange|get|see)\s+(a\s+|your\s+|an?\s+)?(demo|quote|consultation|callback|call)\b"
    r"|\b(contact|talk\s+to|speak\s+(to|with)|chat\s+(to|with))\s+(our\s+)?(sales|sales\s+team|team\s+for\s+pricing)\b"
    r"|\bpricing\s+(is\s+)?(available\s+)?(on|upon)\s+request\b|\bcustom(ised|ized)?\s+pricing\b|\benterprise\s+pricing\b"
    r"|\bcontact\s+us\s+for\s+(pricing|a\s+quote|prices)\b|\bprices?\s+(available\s+)?on\s+(request|application)\b|\bPOA\b", re.I)
FREE_TRIAL_RE = re.compile(r"\bfree\s+trial\b|\btry\s+(it\s+|us\s+)?(for\s+)?free\b|\bstart\s+(for\s+)?free\b|\b\d+[\s\-]day\s+(free\s+)?trial\b", re.I)
FREE_TIER_RE = re.compile(r"\bfree\s+(plan|tier|forever|version|account)\b|\balways\s+free\b|\bfree\s+to\s+use\b|\bno\s+cost\b|\bfree\s+of\s+charge\b", re.I)
UK_POSTCODE_RE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b")
US_CITY_STATE_ZIP_RE = re.compile(r"\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)?,?\s+[A-Z]{2}\s+\d{5}(?:-\d{4})?\b")
STREET_RE = re.compile(
    r"\b\d{1,5}[A-Za-z]?(?:[-–]\d{1,5})?\s+(?:[A-Z][\w'’\-]*\s+){0,3}"
    r"(?:Street|St\.?|Road|Rd\.?|Avenue|Ave\.?|Lane|Ln\.?|Drive|Dr\.?|Boulevard|Blvd\.?|Way|Place|Pl\.?|Square|Sq\.?|Court|Ct\.?|"
    r"Terrace|Crescent|Close|Parade|Highway|Hwy\.?|Route|Row|Gardens|Walk|Quay|Wharf|Broadway|Esplanade|Straße|Strasse|Str\.|Rue|Calle|Via|Avenida|Plaza|Platz|Weg|Allee)\b")
POSTAL_CUE_RE = re.compile(r"\b(suite|floor|fl\.|building|bldg|unit|level|po\s+box|p\.o\.\s+box)\s+\w+", re.I)
# Anglo grammars above assume number-then-street-word ("12 Harbour Street"). Much of the world does not
# write addresses that way, and a grammar that cannot match is indistinguishable from a site with no
# address on it -- the audit then reports "it isn't there" when the truth is "I could not read it".
# The patterns below cover the orders and postcode shapes that were silently invisible.
STREET_REVERSED_RE = re.compile(  # "Hauptstrasse 12", "Via Montenapoleone 8", "Rue du Marche 27"
    r"\b[A-ZÄÖÜ][\wÄÖÜäöüß'’\-]*(?:stra(?:ss|ß)e|str\.|gasse|weg|allee|platz|ring|damm)\s+\d{1,4}\s*[a-z]?\b"
    r"|\b(?:rue|avenue|boulevard|via|viale|calle|carrer|plaza|praca|praça)\s+[\w'’\-\s]{2,40}?\s+\d{1,4}\b", re.I)
# French and Belgian addresses put the street word in lower case after the number ("12 rue des Archives",
# "3 boulevard Saint-Germain"), so the capitalised alternation in STREET_RE never sees them. The proper noun
# after the street word must be capitalised, which keeps "finished in 12th place" and "12 place mats" out.
STREET_FR_RE = re.compile(
    r"\b\d{1,4}(?:\s?(?:bis|ter))?,?\s+(?:rue|avenue|av\.|boulevard|bd|impasse|all[ée]e|chemin|quai|cours|place|route|passage|villa|cit[ée])\s+"
    r"(?:d[eu]s?\s+|de\s+la\s+|de\s+l['’]|du\s+|la\s+|le\s+|l['’])?[A-ZÀ-Ý][\w'’\-]+")
IN_STATES = (r"andhra\s+pradesh|karnataka|kerala|maharashtra|tamil\s+nadu|telangana|gujarat|rajasthan|punjab|"
             r"haryana|west\s+bengal|uttar\s+pradesh|madhya\s+pradesh|bihar|odisha|assam|goa|delhi|chandigarh")
IN_PIN_RE = re.compile(  # a bare six-digit run is far too common to trust; require country, state or a PIN label
    r"\b(?:india|bharat)\b\s*[-–,]?\s*\d{6}\b|\b\d{6}\b\s*,?\s*(?:india|bharat)\b"
    r"|\bpin(?:\s*code)?\s*[-:]?\s*\d{6}\b|\b(?:" + IN_STATES + r")\b\s*[-,]?\s*\d{6}\b", re.I)
EU_POSTCODE_CITY_RE = re.compile(  # "10115 Berlin", "1010 Wien" -- ambiguous on its own, see ADDRESS_GUARDS
    r"(?:^|[,;:]\s*)\d{4,5}\s+[A-ZÄÖÜÀ-Ý][\wäöüßà-ÿ'\-]{2,}\b", re.M)
JP_POSTCODE_RE = re.compile(r"〒\s*\d{3}-?\d{4}\b")

# Corroboration for the shapes a statistic can imitate: "45000 Requests handled" has the same shape as
# "45000 Zurich", and only nearby context separates them. Bare "address" is not a cue -- IP address, email
# address and addressable market all outnumber postal addresses on a typical marketing page.
ADDRESS_CUE_RE = re.compile(
    r"(?:postal|mailing|registered|office|our|head|business|company|visiting)\s+address|\baddress\s*[:\n]"
    r"|sitz\b|adress|anschrift|\bpost\s?code\b|headquarter|si[eè]ge|\bsede\b|direcci[oó]n|indirizzo|hoofdkantoor", re.I)
_COUNTRY = (r"deutschland|germany|[oö]sterreich|austria|schweiz|switzerland|suisse|france|nederland|netherlands|"
            r"belgi\w*|espa[nñ]a|spain|italia|italy|portugal|polska|poland|sverige|sweden|danmark|denmark|norge|norway")
COUNTRY_AFTER_RE = re.compile(r"^[\s,.;·|/-]{0,4}(?:%s)\b" % _COUNTRY, re.I)
COUNTRY_BEFORE_RE = re.compile(r"\b(?:%s)[\s,.;·|/-]{0,4}$" % _COUNTRY, re.I)
# Opening hours in the languages the fixtures and the live pass have actually met. Three things the
# original English-only version got wrong: it knew day names in one language, it could not read the
# day-then-range form "Mo-Fr", and its trailing \b could never match after "5pm" or "18h" because there is
# no word boundary between a digit and a letter -- so "Monday to Friday, 9am - 5pm" was invisible too.
_HOURS_DAYS = (r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun|"
               r"weekdays|weekends|daily|every\s+day|"
               r"montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonnabend|sonntag|werktags|t[aä]glich|"
               r"lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|"
               r"lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo|"
               r"luned[iì]|marted[iì]|mercoled[iì]|gioved[iì]|venerd[iì]|sabato|domenica|"
               r"maandag|dinsdag|woensdag|donderdag|vrijdag|zaterdag|zondag")
# Short day forms are only safe inside a range: bare "do", "so", "mar" and "fr" are ordinary words.
_HOURS_ABBR = r"(?:lun|mar|mer|jeu|ven|sam|dim|mo|di|mi|do|fr|sa|so|lu|ma|me|je|ve)"
_HOURS_DAY_RANGE = r"\b%s\s*[-–—/]\s*%s\b" % (_HOURS_ABBR, _HOURS_ABBR)
_HOURS_TIME = r"\d{1,2}(?:\s?h\s?\d{2}|[:.]\d{2})?(?:\s?(?:am|pm|a\.m\.|p\.m\.|h|uhr))?"   # 9, 09:00, 9.00, 9h30, 5pm
_HOURS_RANGE = r"\b%s\s?(?:-|–|—|to|until|till|bis|à|a|y)\s?%s(?!\d)" % (_HOURS_TIME, _HOURS_TIME)
_HOURS_LABEL = (r"\bopen\s+24\s+hours\b|\b24/7\b|\bopening\s+hours\b|\bhours\s+of\s+operation\b|\bwe\s+are\s+open\b|"
                r"\b[oö]ffnungszeiten\b|\bgesch[aä]ftszeiten\b|\bhoraires?\s+d[’']ouverture\b|"
                r"\bhorario\s+de\s+atenci[oó]n\b|\bhorario\s+comercial\b|\borari\s+di\s+apertura\b|\bopeningstijden\b")
HOURS_RE = re.compile(r"(?:\b(?:%s)\b|%s)[^.\n]{0,60}?%s|%s"
                      % (_HOURS_DAYS, _HOURS_DAY_RANGE, _HOURS_RANGE, _HOURS_LABEL), re.I)
AUD_NOUNS = (r"freelancers?|designers?|developers?|engineers?|marketers?|founders?|creators?|teams?|businesses|business\s+owners|companies|startups?|"
             r"enterprises?|agencies|studios|students?|teachers?|schools|universities|families|parents|kids|children|homeowners|renters|"
             r"professionals|clients|customers|shoppers|small\s+businesses|smbs?|nonprofits?|charities|organi[sz]ations|individuals|people|users|brands|"
             r"retailers|sellers|buyers|merchants|publishers|patients|doctors|clinics|dentists|lawyers|law\s+firms|accountants|architects|"
             r"photographers|artists|illustrators|writers|authors|musicians|restaurants|cafes|hotels|travellers|travelers|athletes|runners|gamers|"
             r"investors|traders|recruiters|hr\s+teams|sales\s+teams|it\s+teams|product\s+teams|researchers|scientists|educators|"
             r"contractors|builders|plumbers|electricians|landlords|tenants|drivers|fleets|farmers|manufacturers|distributors|wholesalers|"
             r"local\s+businesses|communities|members|volunteers|donors|readers|listeners|viewers|fans|everyone|anyone")
AUDIENCE_RE = re.compile(r"\b(?:built|designed|made|created|tailored|perfect|ideal|trusted|used|loved)\s+(?:for|by)\s+(?:[\w,.'’\-]+\s+){0,4}?(?:%s)\b"
                         r"|\b(?:for|helps?|helping|serving|serves)\s+(?:[\w,.'’\-]+\s+){0,3}?(?:%s)\b" % (AUD_NOUNS, AUD_NOUNS), re.I)
LOCATION_PHRASE_RE = re.compile(r"\b(?:based|headquartered|located|founded|offices?|serving|we\s+serve|operating)\s+(?:in|across|throughout|from)\s+"
                                r"((?:[A-Z][\w\-.’']+)(?:[ ,]+(?:[A-Z][\w\-.’']+|and|the|of)){0,4})")
MISSION_RE = re.compile(r"\b((?:the\s+)?mission\s+of\s+(?:the\s+)?[\w&.\-' ]{2,60}?\s+is\s+to|our\s+mission|mission\s+is|we\s+exist\s+to|our\s+purpose|our\s+vision|we\s+believe|dedicated\s+to|committed\s+to|"
                        r"we\s+work\s+to|founded\s+to|our\s+goal\s+is|our\s+aim\s+is|we\s+aim\s+to|we\s+strive\s+to)\b[^.!?\n]{10,220}", re.I)
PARTICIPATE_RE = re.compile(r"\b(donate|give\s+now|give\s+today|make\s+a\s+(gift|donation)|apply\s+now|apply|admissions?|enrol|enroll|volunteer|join\s+us|"
                            r"join|become\s+a\s+member|membership|register|get\s+involved|support\s+us|sponsor|fundraise|take\s+action|sign\s+the\s+petition)\b", re.I)
LEADERSHIP_RE = re.compile(r"\b(ceo|chief\s+executive(\s+officer)?|chief\s+(operating|financial|technology|technical|marketing|product|revenue)\s+officer|"
                           r"c[ofmtp]o|founder|co-?founder|managing\s+director|executive\s+director|president|chair(man|woman|person)?|general\s+manager|"
                           r"head\s+of\s+\w+|vice\s+president|managing\s+partner|principal|owner|proprietor)\b", re.I)
SIZE_RE = re.compile(r"\b(\d[\d,.]*\s?(?:k|\+)?|hundreds\s+of|thousands\s+of|dozens\s+of|over\s+\d[\d,]*|more\s+than\s+\d[\d,]*)\s+(employees|people|staff|team\s+members|colleagues|engineers|specialists)\b", re.I)
SIGNUP_RE = re.compile(r"\b(sign\s*up|get\s+started|start\s+(now|free|your\s+free|today|a\s+free)|create\s+(an\s+)?account|try\s+(it\s+)?(for\s+)?free|"
                       r"book\s+a\s+demo|request\s+a\s+demo|start\s+free\s+trial|free\s+trial|join\s+now|subscribe|download)\b", re.I)
# The sampler already recognises "presse"/"aktuelles"/"noticias" as blog-role nav labels; this pattern did
# not, so a German press page was found as a page and then judged not to be a press surface. Note that
# \bpress\b cannot match "Presse" -- the trailing "e" is a word character -- so each form is spelled out.
PRESS_RE = re.compile(r"\b(press|media|newsroom|news\s*room|media\s+(enquiries|inquiries|relations|kit)|"
                      r"press\s+(kit|office|releases?|contact)|pr\s+contact|journalists?|"
                      r"presse|pressemitteilung(en)?|pressekontakt|pressemappe|medien|medienmitteilung(en)?|"
                      r"presse-?kit|salle\s+de\s+presse|communiqu[eé]s?\s+de\s+presse|"
                      r"prensa|sala\s+de\s+prensa|notas?\s+de\s+prensa|"
                      r"ufficio\s+stampa|comunicati\s+stampa|"
                      r"persbericht(en)?|perskit)\b", re.I)
PRESS_EMAIL_RE = re.compile(r"\b(press|media|pr|news|comms|communications)@", re.I)
SHIPPING_RETURNS_RE = re.compile(r"\b(shipping|delivery|deliver(y|ies)|returns?|refunds?|exchanges?|return\s+policy|money[\s\-]back)\b", re.I)
DIFFERENTIATOR_RE = re.compile(r"\b(unlike|the\s+only|the\s+first|first\s+and\s+only|no\s+other|what\s+sets\s+us\s+apart|why\s+choose|why\s+us|our\s+difference|"
                               r"compared\s+to|better\s+than|instead\s+of|the\s+most\s+\w+|world'?s\s+\w+est|#1|number\s+one|award[\s\-]winning)\b[^.!?\n]{5,180}", re.I)
ROLE_STATEMENT_RE = re.compile(r"\b(I\s+am|I'm|I’m|we\s+are|we're|we’re)\s+(a|an|the)\s+([^.,;!?\n]{3,80})", re.I)
NAME_RE = re.compile(r"^[A-Z][a-zà-ÿ'’\-]+(?:\s+(?:[A-Z][a-zà-ÿ'’\-]+|de|van|von|da|del|la|le|bin|al)){1,3}$")
ISO_DATE_RE = re.compile(r"\b(19|20)\d{2}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b")
TEXT_DATE_RE = re.compile(r"\b(?:\d{1,2}(?:st|nd|rd|th)?\s+)?(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(?:\d{1,2}(?:st|nd|rd|th)?,?\s+)?(19|20)\d{2}\b", re.I)
COPYRIGHT_RE = re.compile(r"(?:©|\(c\)|copyright)\s*(?:(?:19|20)\d{2}(?:\s*[-–]\s*(?:19|20)\d{2})?\s*)?([A-Z][\w&.,'’\- ]{2,60}?)(?=\.|,|\s+all\s+rights|\s*$|\s+·|\s+\|)", re.I | re.M)
PROFILE_HOSTS = ("instagram.com", "linkedin.com", "behance.net", "dribbble.com", "github.com", "twitter.com", "x.com", "facebook.com",
                 "youtube.com", "tiktok.com", "vimeo.com", "medium.com", "substack.com", "mastodon", "bsky.app", "threads.net", "pinterest.com")
# Hosts whose page about a brand pins its name to one entity: knowledge graphs, professional networks, and the
# company registers (or their public mirrors) of the countries the address grammars cover, plus review and place
# listings that carry a stable identifier for a business the way Trustpilot does. Matched as substrings of the
# host, so "tripadvisor." covers every country edition and "northdata." both .de and .com. A Paris bistro whose
# only anchors were TripAdvisor and societe.com was told it had "only social profiles"; that was the Anglo
# register list talking, not the site.
AUTHORITY_HOSTS = ("wikidata.org", "wikipedia.org", "linkedin.com", "crunchbase.com", "companieshouse", "company-information.service.gov.uk",
                   "opencorporates.com", "sec.gov", "dnb.com", "bloomberg.com", "glassdoor.com", "g2.com", "trustpilot.com",
                   "societe.com", "pappers.fr", "infogreffe.fr", "handelsregister.de", "northdata.", "unternehmensregister.de",
                   "zefix.ch", "kvk.nl", "registroimprese.it", "abr.business.gov.au", "asic.gov.au", "bizfile.gov.sg",
                   "companiesoffice.govt.nz", "zaubacorp.com", "tofler.in", "mca.gov.in", "cvr.dk", "brreg.no",
                   "tripadvisor.", "yelp.com", "maps.app.goo.gl")
GENERIC_HEADINGS = ("contact", "about", "faq", "frequently asked", "related", "latest", "news", "newsletter", "follow", "footer", "menu",
                    "navigation", "search", "log in", "login", "sign in", "legal", "privacy", "terms", "cookie", "subscribe", "share", "leadership",
                    "where we are", "press", "security", "who it is for", "who we are", "what we do", "trusted by")
GENERIC_TITLES = {"home", "home page", "homepage", "untitled", "untitled document", "welcome", "index", "new page", "default", "page", "site", "website", "document"}
FAQ_HEADING_RE = re.compile(r"\bfaqs?\b|frequently\s+asked|common\s+questions|questions\s*(and|&)\s*answers|\bq\s*&\s*a\b|got\s+questions|your\s+questions", re.I)

# ------------------------------------------------------------------ schema.org type tables
LOCAL_BUSINESS_TYPES = {"LocalBusiness", "Restaurant", "Store", "Dentist", "Physician", "MedicalClinic", "Hotel", "LodgingBusiness", "FoodEstablishment",
                        "CafeOrCoffeeShop", "Bakery", "BarOrPub", "AutoRepair", "HairSalon", "BeautySalon", "HealthAndBeautyBusiness",
                        "HomeAndConstructionBusiness", "Plumber", "Electrician", "RealEstateAgent", "SportsActivityLocation", "ExerciseGym",
                        "AutomotiveBusiness", "ChildCare", "DryCleaningOrLaundry", "EmergencyService", "EntertainmentBusiness", "FinancialService",
                        "GovernmentOffice", "LegalService", "Library", "MedicalBusiness", "ShoppingCenter", "TravelAgency", "VeterinaryCare",
                        "ProfessionalService", "Attorney", "AccountingService", "InsuranceAgency", "EmploymentAgency", "Notary", "AdvertisingAgency",
                        "AnimalShelter", "ArchiveOrganization", "ArtGallery", "Casino", "Dentist", "Florist", "GasStation", "HardwareStore",
                        "HobbyShop", "HomeGoodsStore", "JewelryStore", "LiquorStore", "MensClothingStore", "MobilePhoneStore", "MovieTheater",
                        "MusicStore", "NightClub", "OfficeEquipmentStore", "OutletStore", "PawnShop", "PetStore", "Pharmacy", "Optician",
                        "RadioStation", "RecyclingCenter", "SelfStorage", "ShoeStore", "SportingGoodsStore", "TelevisionStation", "TireShop",
                        "ToyStore", "WholesaleStore", "Winery", "Brewery", "Distillery", "IceCreamShop", "FastFoodRestaurant", "MovingCompany",
                        "HousePainter", "Locksmith", "RoofingContractor", "GeneralContractor", "HVACBusiness", "DaySpa", "NailSalon", "TattooParlor"}
ORG_TYPES = LOCAL_BUSINESS_TYPES | {"Organization", "Corporation", "NGO", "EducationalOrganization", "CollegeOrUniversity", "School", "HighSchool",
                                    "ElementarySchool", "MiddleSchool", "Preschool", "GovernmentOrganization", "NewsMediaOrganization",
                                    "MedicalOrganization", "SportsOrganization", "SportsTeam", "PerformingGroup", "MusicGroup", "Airline",
                                    "Consortium", "LibrarySystem", "OnlineBusiness", "OnlineStore", "ResearchOrganization", "WorkersUnion",
                                    "FundingScheme", "FundingAgency", "Cooperative", "Project", "Church", "PlaceOfWorship", "Hospital",
                                    "Consultant", "MarketingAgency", "DesignAgency", "Brand"}
# required = the node cannot identify the thing without these; any_of = at least one of the group must exist.
# recommended = recorded for proactive recommendations, never a finding.
REQUIRED_PROPS = {
    "Organization": {"required": ["name", "url"], "any_of": [], "recommended": ["logo", "sameAs", "description", "address", "contactPoint"]},
    "LocalBusiness": {"required": ["name", "address"], "any_of": [], "recommended": ["telephone", "openingHoursSpecification", "geo", "url", "priceRange", "image"]},
    "Person": {"required": ["name"], "any_of": [], "recommended": ["jobTitle", "url", "sameAs", "image"]},
    "SoftwareApplication": {"required": ["name"], "any_of": [["offers", "aggregateRating", "review"]], "recommended": ["applicationCategory", "operatingSystem", "offers", "aggregateRating"]},
    "WebApplication": {"required": ["name"], "any_of": [["offers", "aggregateRating", "review"]], "recommended": ["applicationCategory", "operatingSystem", "offers"]},
    "MobileApplication": {"required": ["name"], "any_of": [["offers", "aggregateRating", "review"]], "recommended": ["applicationCategory", "operatingSystem", "offers"]},
    "Product": {"required": ["name"], "any_of": [["offers", "aggregateRating", "review"]], "recommended": ["image", "description", "brand", "sku"]},
    "Service": {"required": ["name"], "any_of": [], "recommended": ["provider", "areaServed", "serviceType", "offers"]},
    "Article": {"required": ["headline"], "any_of": [], "recommended": ["author", "datePublished", "dateModified", "image", "publisher"]},
    "NewsArticle": {"required": ["headline"], "any_of": [], "recommended": ["author", "datePublished", "dateModified", "image", "publisher"]},
    "BlogPosting": {"required": ["headline"], "any_of": [], "recommended": ["author", "datePublished", "dateModified", "image", "publisher"]},
    "TechArticle": {"required": ["headline"], "any_of": [], "recommended": ["author", "datePublished", "dateModified"]},
    "FAQPage": {"required": ["mainEntity"], "any_of": [], "recommended": []},
    "BreadcrumbList": {"required": ["itemListElement"], "any_of": [], "recommended": []},
    "ItemList": {"required": ["itemListElement"], "any_of": [], "recommended": []},
    "Event": {"required": ["name", "startDate", "location"], "any_of": [], "recommended": ["endDate", "offers", "performer", "organizer", "image"]},
    "JobPosting": {"required": ["title", "description", "datePosted", "hiringOrganization", "jobLocation"], "any_of": [], "recommended": ["baseSalary", "employmentType", "validThrough"]},
    "Recipe": {"required": ["name", "image"], "any_of": [], "recommended": ["author", "recipeIngredient", "recipeInstructions"]},
    "VideoObject": {"required": ["name", "thumbnailUrl", "uploadDate"], "any_of": [], "recommended": ["description", "duration", "contentUrl"]},
    "Review": {"required": ["itemReviewed"], "any_of": [["reviewRating", "reviewBody"]], "recommended": ["author"]},
    "WebSite": {"required": ["url"], "any_of": [], "recommended": ["name", "publisher", "potentialAction"]},
    "Course": {"required": ["name", "description"], "any_of": [], "recommended": ["provider"]},
    "Book": {"required": ["name"], "any_of": [], "recommended": ["author", "isbn"]},
}


def spec_for(types):
    """Pick the REQUIRED_PROPS entry for a node's types: exact match first, then LocalBusiness/Organization families."""
    for t in types:
        if t in REQUIRED_PROPS:
            return t, REQUIRED_PROPS[t]
    for t in types:
        if t in LOCAL_BUSINESS_TYPES:
            return "LocalBusiness", REQUIRED_PROPS["LocalBusiness"]
    for t in types:
        if t in ORG_TYPES:
            return "Organization", REQUIRED_PROPS["Organization"]
    return None, None


# ------------------------------------------------------------------ JSON-LD helpers
def node_types(node):
    t = node.get("@type") if isinstance(node, dict) else None
    if isinstance(t, list):
        return [x for x in t if isinstance(x, str)]
    return [t] if isinstance(t, str) else []


def top_level_nodes(data):
    """Top-level nodes of a JSON-LD block: the object itself, list items, and @graph members. Nested objects excluded."""
    out = []
    if isinstance(data, dict):
        if isinstance(data.get("@graph"), list):
            out.extend(n for n in data["@graph"] if isinstance(n, dict))
            if node_types(data):
                out.append(data)
        else:
            out.append(data)
    elif isinstance(data, list):
        for item in data:
            out.extend(top_level_nodes(item))
    return out


def doc_top_nodes(doc):
    """[(node, block_index)] for every parsed block of a Document."""
    out = []
    for i, b in enumerate(doc.jsonld):
        if b["data"] is None:
            continue
        for n in top_level_nodes(b["data"]):
            out.append((n, i))
    return out


def _present(v):
    if v is None:
        return False
    if isinstance(v, (str, list, dict)):
        return len(v) > 0 and (not isinstance(v, str) or v.strip() != "")
    return True


def missing_required(node):
    """(spec_type, missing_required, unmet_any_of_groups) for a known top-level node, or (None, [], []) when not graded."""
    types = node_types(node)
    spec_type, spec = spec_for(types)
    if not spec:
        return None, [], []
    missing = [p for p in spec["required"] if not _present(node.get(p))]
    unmet = [grp for grp in spec["any_of"] if not any(_present(node.get(p)) for p in grp)]
    return spec_type, missing, unmet


def missing_recommended(node):
    spec_type, spec = spec_for(node_types(node))
    if not spec:
        return None, []
    return spec_type, [p for p in spec["recommended"] if not _present(node.get(p))]


def is_org_node(node, allow_person=False):
    ts = node_types(node)
    return any(t in ORG_TYPES for t in ts) or (allow_person and "Person" in ts)


def jsonld_strings(node, keys=("description", "name", "slogan", "jobTitle", "priceRange", "openingHours", "telephone", "email", "streetAddress",
                                "addressLocality", "addressRegion", "postalCode", "addressCountry", "audience", "areaServed", "knowsAbout")):
    """Leaf string values under selected keys, walking nested objects."""
    out = []

    def walk(v, key=None):
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x, k)
        elif isinstance(v, list):
            for x in v:
                walk(x, key)
        elif isinstance(v, str) and key in keys:
            out.append(v)
    walk(node)
    return out


# ------------------------------------------------------------------ text helpers
def _clip(s, n=200):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[:n - 1] + "…"


def _found(value, page, source):
    return {"value": _clip(value), "page": page.final_url if hasattr(page, "final_url") else page, "source": source}


def _ctx(text, m, before=40, after=100):
    """Excerpt around a regex match, snapped to word boundaries, with ellipses where text was cut."""
    s, e = m.start(), m.end()
    a, b = max(0, s - before), min(len(text), e + after)
    if a > 0:
        ws = text.find(" ", a, s)
        if ws != -1:
            a = ws + 1
    if b < len(text):
        ws = text.rfind(" ", e, b)
        if ws != -1:
            b = ws
    out = text[a:b].strip()
    return ("…" if a > 0 else "") + out + ("…" if b < len(text) else "")


def page_text(page):
    """Searchable text for a page: visible body text plus meta description plus JSON-LD leaf strings (capped)."""
    d = page.doc
    parts = [d.body_text or ""]
    md = d.meta("description", "og:description")
    if md:
        parts.append(md)
    for n, _ in doc_top_nodes(d):
        parts.extend(jsonld_strings(n))
    return " \n ".join(parts)[:400000]


def _ordered(pages, prefer=()):
    pref = [p for r in prefer for p in pages if p.role == r]
    rest = [p for p in pages if p not in pref]
    return pref + rest


def _link_texts(page):
    return [(l.text or "", l) for l in page.doc.links]


def _headings(page, min_level=1, max_level=3):
    return [h for h in page.doc.headings if h["tag"] in ("h%d" % i for i in range(min_level, max_level + 1))]


# ------------------------------------------------------------------ detectors
def find_price(pages, prefer=("pricing", "product", "home")):
    for p in _ordered(pages, prefer):
        t = page_text(p)
        m = PRICE_RE.search(t)
        if m:
            return _found(_ctx(t, m, 30, 40), p, "text")
        for n, _ in doc_top_nodes(p.doc):
            for offer in _walk_offers(n):
                if _present(offer.get("price")) or _present(offer.get("lowPrice")):
                    return _found("%s %s" % (offer.get("price") or offer.get("lowPrice"), offer.get("priceCurrency") or ""), p, "jsonld:Offer.price")
    return None


def _walk_offers(node):
    if isinstance(node, dict):
        if "Offer" in node_types(node) or "AggregateOffer" in node_types(node):
            yield node
        for k, v in node.items():
            if k.startswith("@"):
                continue
            for o in _walk_offers(v):
                yield o
    elif isinstance(node, list):
        for x in node:
            for o in _walk_offers(x):
                yield o


def find_sales_led(pages, roles=None):
    for p in pages:
        if roles and p.role not in roles:
            continue
        t = page_text(p)
        m = SALES_LED_RE.search(t)
        if m:
            return _found(_ctx(t, m), p, "text")
        for text, l in _link_texts(p):
            if SALES_LED_RE.search(text):
                return _found(text, p, "link")
    return None


def find_free_trial(pages):
    for p in pages:
        t = page_text(p)
        m = FREE_TRIAL_RE.search(t)
        if m:
            return _found(_ctx(t, m, 30, 40), p, "text")
    return None


def find_free_tier(pages):
    for p in pages:
        t = page_text(p)
        m = FREE_TIER_RE.search(t)
        if m:
            return _found(_ctx(t, m, 30, 40), p, "text")
    return None


def find_email(pages, prefer=("contact", "home")):
    for p in _ordered(pages, prefer):
        for l in p.doc.links:
            if l.href.lower().startswith("mailto:"):
                return _found(l.href[7:].split("?")[0], p, "link:mailto")
        m = EMAIL_RE.search(page_text(p))
        if m and not m.group(0).lower().endswith((".png", ".jpg", ".svg", ".gif")):
            return _found(m.group(0), p, "text")
    return None


# A phone number is claimed from text only with a "+" prefix or a cue word in front of it. The cues were
# English-only and PHONE_TEXT_RE wants 3-4 digit groups, so "Telefon: 0211 - 63 55 33 55" -- the ordinary
# German format -- was invisible and the site was told to add a number it already shows. This second pass
# reads whatever follows a cue in any of the audit's languages, in whatever grouping the country uses. It
# still requires the cue, which is what keeps bare digit runs (order numbers, years) from counting.
_PHONE_CUES = (r"phone|telephone|tel|call|mobile|cell|whatsapp|fax|ph|"
               r"telefon|telefono|tel[eé]fono|t[eé]l[eé]phone|t[eé]l|rufnummer|hotline|fon|telefoon")
PHONE_AFTER_CUE_RE = re.compile(r"\b(?:%s)\b[\s.:]{0,4}((?:\+|00)?[\d(][\d\s.\-/()]{5,24}\d)" % _PHONE_CUES, re.I)


def text_phone(text):
    """First phone number stated as text, or None. Shared by find_phone and the entity probe's NAP check."""
    t = text or ""
    for m in PHONE_TEXT_RE.finditer(t):
        digits = sum(c.isdigit() for c in m.group(0))
        if 9 <= digits <= 15:
            before = t[max(0, m.start() - 30):m.start()]
            if m.group(0).strip().startswith("+") or PHONE_CUE_RE.search(before):
                return m.group(0)
    for m in PHONE_AFTER_CUE_RE.finditer(t):
        if 8 <= sum(c.isdigit() for c in m.group(1)) <= 15:
            return m.group(1).strip()
    return None


def find_phone(pages, prefer=("contact", "home")):
    for p in _ordered(pages, prefer):
        for l in p.doc.links:
            if l.href.lower().startswith("tel:"):
                return _found(l.href[4:], p, "link:tel")
        for n, _ in doc_top_nodes(p.doc):
            for v in jsonld_strings(n, keys=("telephone",)):
                if sum(c.isdigit() for c in v) >= 7:
                    return _found(v, p, "jsonld:telephone")
    for p in _ordered(pages, prefer):
        hit = text_phone(page_text(p))
        if hit:
            return _found(hit, p, "text")
    return None


def find_contact_form(pages):
    for p in _ordered(pages, ("contact",)):
        for f in p.doc.forms:
            names = " ".join((i.get("name") or "") + " " + (i.get("type") or "") for i in f["inputs"]).lower()
            if "email" in names or "message" in names or (p.role == "contact" and f["inputs"]):
                return _found("contact form (%d fields)" % len(f["inputs"]), p, "form")
    return None


def find_contact(pages):
    return find_email(pages) or find_phone(pages) or find_contact_form(pages)


def _guard_word_before(text, m):
    """A UK-postcode shape with no word before it is usually a product code or a reference number."""
    return bool(re.search(r"[A-Za-z]{3,}", text[max(0, m.start() - 40):m.start()]))


def _guard_address_context(text, m):
    """A postcode-and-city shape needs corroboration: a postal-address cue nearby, or a country name adjacent."""
    if ADDRESS_CUE_RE.search(text[max(0, m.start() - 60):m.end() + 40]):
        return True
    return bool(COUNTRY_AFTER_RE.search(text[m.end():m.end() + 30])
                or COUNTRY_BEFORE_RE.search(text[max(0, m.start() - 30):m.start()]))


# Order matters only for which label is reported; every pattern is tried before giving up.
ADDRESS_PATTERNS = ((STREET_RE, "street"), (STREET_REVERSED_RE, "street"), (STREET_FR_RE, "street"),
                    (UK_POSTCODE_RE, "uk_postcode"), (US_CITY_STATE_ZIP_RE, "us_city_state_zip"),
                    (IN_PIN_RE, "in_pin"), (EU_POSTCODE_CITY_RE, "eu_postcode_city"),
                    (JP_POSTCODE_RE, "jp_postcode"))
ADDRESS_GUARDS = {"uk_postcode": _guard_word_before, "eu_postcode_city": _guard_address_context}


def address_match(text):
    """First address-shaped span in text as (match, label), or None.

    Shared by find_address here and the entity probe's plain-text NAP check so the two cannot drift apart.
    Guarded patterns scan every occurrence: the first candidate may be a statistic while a later one on the
    same page is the real footer address.
    """
    t = text or ""
    for rx, label in ADDRESS_PATTERNS:
        guard = ADDRESS_GUARDS.get(label)
        for m in rx.finditer(t):
            if guard and not guard(t, m):
                continue
            return m, label
    return None


def find_address(pages, prefer=("contact", "about", "home")):
    for p in _ordered(pages, prefer):
        for n, _ in doc_top_nodes(p.doc):
            addr = _walk_key(n, "address")
            for a in addr:
                if isinstance(a, dict) and (_present(a.get("streetAddress")) or (_present(a.get("addressLocality")) and _present(a.get("postalCode")))):
                    return _found(", ".join(str(a.get(k)) for k in ("streetAddress", "addressLocality", "postalCode", "addressCountry") if _present(a.get(k))), p, "jsonld:PostalAddress")
                if isinstance(a, str) and len(a) > 10:
                    return _found(a, p, "jsonld:address")
    for p in _ordered(pages, prefer):
        t = p.doc.body_text or ""
        hit = address_match(t)
        if hit:
            m, label = hit
            return _found(_ctx(t, m, 40, 30), p, "text:" + label)
    return None


def _walk_key(node, key):
    out = []
    if isinstance(node, dict):
        if key in node:
            v = node[key]
            out.extend(v if isinstance(v, list) else [v])
        for k, v in node.items():
            if not k.startswith("@") and k != key:
                out.extend(_walk_key(v, key))
    elif isinstance(node, list):
        for x in node:
            out.extend(_walk_key(x, key))
    return out


def find_hours(pages, prefer=("contact", "home", "product")):
    for p in _ordered(pages, prefer):
        for n, _ in doc_top_nodes(p.doc):
            if _walk_key(n, "openingHoursSpecification") or _walk_key(n, "openingHours"):
                v = (_walk_key(n, "openingHours") or ["openingHoursSpecification"])[0]
                return _found(v if isinstance(v, str) else "openingHoursSpecification", p, "jsonld:openingHours")
    for p in _ordered(pages, prefer):
        t = p.doc.body_text or ""
        m = HOURS_RE.search(t)
        if m:
            return _found(_ctx(t, m, 20, 40), p, "text")
    return None


def find_description(pages, prefer=("home", "about", "product")):
    for p in _ordered(pages, prefer):
        md = p.doc.meta("description")
        if md and len(md) >= 40:
            return _found(md, p, "meta:description")
    for p in _ordered(pages, prefer):
        od = p.doc.meta("og:description")
        if od and len(od) >= 40:
            return _found(od, p, "meta:og:description")
        for n, _ in doc_top_nodes(p.doc):
            d = n.get("description")
            if isinstance(d, str) and len(d) >= 40:
                return _found(d, p, "jsonld:%s.description" % (node_types(n) or ["?"])[0])
    for p in _ordered(pages, prefer):
        h1 = p.doc.h1s[0] if p.doc.h1s else ""
        if len(h1.split()) >= 3:
            body = p.doc.body_text or ""
            i = body.find(h1)
            para = body[i + len(h1): i + len(h1) + 400] if i >= 0 else body[:400]
            if len(para.split()) >= 12:
                return _found(h1 + " — " + para, p, "heading+text")
    return None


def find_audience(pages, prefer=("home", "about", "product")):
    for p in _ordered(pages, prefer):
        for n, _ in doc_top_nodes(p.doc):
            aud = _walk_key(n, "audience")
            if aud:
                a = aud[0]
                return _found(a.get("audienceType") or a.get("name") or "audience" if isinstance(a, dict) else a, p, "jsonld:audience")
    for p in _ordered(pages, prefer):
        t = page_text(p)
        m = AUDIENCE_RE.search(t)
        if m:
            return _found(_ctx(t, m, 20, 30), p, "text")
    return None


def find_offer_list(pages, prefer=("product", "home", "blog"), min_items=3, jsonld_types=("Product", "Service", "Menu", "MenuItem", "ItemList", "Offer", "Course", "Event")):
    for p in _ordered(pages, prefer):
        names = []
        for n, _ in doc_top_nodes(p.doc):
            if any(t in jsonld_types for t in node_types(n)) and _present(n.get("name")):
                names.append(str(n.get("name")))
            for item in _walk_key(n, "itemListElement"):
                if isinstance(item, dict):
                    nm = item.get("name") or (item.get("item") or {}).get("name") if isinstance(item.get("item"), dict) else item.get("name")
                    if nm and "BreadcrumbList" not in node_types(n):
                        names.append(str(nm))
        if len(names) >= min_items:
            return _found("; ".join(names[:5]), p, "jsonld")
    for p in _ordered(pages, prefer):
        hs = [h["text"] for h in _headings(p, 2, 3) if h["text"] and not any(g in h["text"].lower() for g in GENERIC_HEADINGS) and len(h["text"].split()) <= 8]
        if len(hs) >= min_items:
            return _found("; ".join(hs[:5]), p, "heading")
    for p in _ordered(pages, prefer):
        if p.role in ("product", "blog"):
            items = [l.text for l in p.doc.internal_links if l.context in ("main", "body", "article") and 2 <= len((l.text or "").split()) <= 10]
            if len(items) >= min_items:
                return _found("; ".join(items[:5]), p, "link")
    return None


def find_location_phrase(pages, prefer=("about", "home", "contact")):
    for p in _ordered(pages, prefer):
        for n, _ in doc_top_nodes(p.doc):
            for a in _walk_key(n, "address"):
                if isinstance(a, dict) and _present(a.get("addressLocality")):
                    return _found(", ".join(str(a.get(k)) for k in ("addressLocality", "addressRegion", "addressCountry") if _present(a.get(k))), p, "jsonld:PostalAddress")
            for v in _walk_key(n, "areaServed"):
                if isinstance(v, str) and v:
                    return _found(v, p, "jsonld:areaServed")
    for p in _ordered(pages, prefer):
        t = p.doc.body_text or ""
        m = LOCATION_PHRASE_RE.search(t)
        if m:
            return _found(m.group(0), p, "text")
    return None


def find_dates(pages):
    for p in pages:
        if p.doc.times:
            return _found(p.doc.times[0], p, "html:time")
    for p in pages:
        for n, _ in doc_top_nodes(p.doc):
            for k in ("datePublished", "dateModified"):
                v = n.get(k)
                if isinstance(v, str) and v:
                    return _found(v, p, "jsonld:%s" % k)
    for p in pages:
        t = p.doc.body_text or ""
        m = ISO_DATE_RE.search(t) or TEXT_DATE_RE.search(t)
        if m:
            return _found(m.group(0), p, "text")
    return None


def find_publisher_identity(pages):
    for p in _ordered(pages, ("home", "about")):
        for n, _ in doc_top_nodes(p.doc):
            if is_org_node(n) and _present(n.get("name")):
                return _found(n["name"], p, "jsonld:%s.name" % node_types(n)[0])
        sn = p.doc.meta("og:site_name", "application-name")
        if sn:
            return _found(sn, p, "meta:og:site_name")
    for p in pages:
        m = COPYRIGHT_RE.search(p.doc.body_text or "")
        if m:
            return _found(m.group(1), p, "text:copyright")
    return None


def find_person(pages):
    for p in _ordered(pages, ("home", "about")):
        for n, _ in doc_top_nodes(p.doc):
            if "Person" in node_types(n) and _present(n.get("name")):
                return _found(n["name"], p, "jsonld:Person.name")
    for p in _ordered(pages, ("home", "about")):
        for h in p.doc.h1s:
            words = h.split()
            if 2 <= len(words) <= 4 and NAME_RE.match(h.strip()):
                return _found(h, p, "heading:h1")
            m = re.match(r"^([A-Z][\w'’\-]+(?:\s+[A-Z][\w'’\-]+){1,2})\b", h)
            if m and len(words) <= 12:
                return _found(m.group(1), p, "heading:h1")
        title = p.doc.title or ""
        seg = re.split(r"\s+[|—–-]\s+|\s*:\s+", title)[0].strip()
        if NAME_RE.match(seg):
            return _found(seg, p, "title")
    return None


def find_role_statement(pages):
    for p in _ordered(pages, ("home", "about")):
        for n, _ in doc_top_nodes(p.doc):
            if "Person" in node_types(n) and _present(n.get("jobTitle")):
                return _found(n["jobTitle"], p, "jsonld:Person.jobTitle")
    for p in _ordered(pages, ("home", "about")):
        t = p.doc.body_text or ""
        m = ROLE_STATEMENT_RE.search(t)
        if m:
            return _found(m.group(0), p, "text")
        title = p.doc.title or ""
        parts = re.split(r"\s+[|—–-]\s+", title)
        if len(parts) >= 2 and len(parts[1].split()) >= 2:
            return _found(parts[1], p, "title")
        if p.doc.h1s and len(p.doc.h1s[0].split()) >= 4:
            return _found(p.doc.h1s[0], p, "heading:h1")
    return None


def find_profile_links(pages):
    for p in pages:
        for n, _ in doc_top_nodes(p.doc):
            sa = _walk_key(n, "sameAs")
            urls = [u for u in sa if isinstance(u, str) and u.startswith("http")]
            if urls:
                return _found(", ".join(urls[:3]), p, "jsonld:sameAs")
        for l in p.doc.links:
            h = (urlsplit(l.url).hostname or "").lower()
            if any(ph in h for ph in PROFILE_HOSTS):
                return _found(l.url, p, "link:profile")
    return None


def find_by_regex(pages, rx, prefer=("home", "about"), source="text", use_links=False, use_headings=False):
    for p in _ordered(pages, prefer):
        t = page_text(p)
        m = rx.search(t)
        if m:
            return _found(_ctx(t, m, 20, 60), p, source)
        if use_headings:
            for h in p.doc.headings:
                if rx.search(h["text"] or ""):
                    return _found(h["text"], p, "heading")
        if use_links:
            for text, l in _link_texts(p):
                if rx.search(text):
                    return _found(text, p, "link")
            for b in p.doc.buttons:
                if rx.search(b.get("text") or ""):
                    return _found(b["text"], p, "button")
    return None


def find_mission(pages):
    f = find_by_regex(pages, MISSION_RE, prefer=("about", "home"))
    if f:
        return f
    for p in _ordered(pages, ("home", "about")):
        for n, _ in doc_top_nodes(p.doc):
            if any(t in ("NGO", "EducationalOrganization", "GovernmentOrganization", "Organization") for t in node_types(n)) and isinstance(n.get("description"), str) and len(n["description"]) >= 40:
                return _found(n["description"], p, "jsonld:description")
    return None


def find_participation(pages):
    return find_by_regex(pages, PARTICIPATE_RE, prefer=("home", "product", "about"), use_links=True, use_headings=True)


def _leadership_value(key, v):
    """The quotable text of a leadership or size property, or None.

    schema.org writes numberOfEmployees as a QuantitativeValue ({"value": 12400}) and founder as a Person;
    reading only `name` returned an empty string for the count, and an empty string became a "present" fact
    the simulation then quoted as nothing.
    """
    if isinstance(v, list):
        v = v[0] if v else None
    if isinstance(v, dict):
        v = v.get("name") or v.get("value") or v.get("minValue")
    if v is None or v == "" or isinstance(v, (dict, list)):
        return None
    if key == "numberOfEmployees" and not isinstance(v, str):
        return "%s employees" % v
    return str(v)


def find_leadership_or_size(pages):
    for p in _ordered(pages, ("about", "home")):
        for n, _ in doc_top_nodes(p.doc):
            for k in ("numberOfEmployees", "founder", "founders", "employee", "member"):
                v = _leadership_value(k, n.get(k))
                if v:
                    return _found(v, p, "jsonld:%s" % k)
        t = p.doc.body_text or ""
        m = LEADERSHIP_RE.search(t) or SIZE_RE.search(t)
        if m:
            return _found(_ctx(t, m, 40, 40), p, "text")
    return None


def find_signup(pages):
    return find_by_regex(pages, SIGNUP_RE, prefer=("home", "pricing", "product"), use_links=True)


def find_press_contact(pages):
    for p in pages:
        m = PRESS_EMAIL_RE.search(page_text(p))
        if m:
            return _found(_ctx(page_text(p), m, 0, 40), p, "text:press_email")
    return find_by_regex(pages, PRESS_RE, prefer=("about", "contact", "blog", "home"), use_links=True, use_headings=True)


def find_shipping_returns(pages):
    return find_by_regex(pages, SHIPPING_RETURNS_RE, prefer=("product", "home", "contact"), use_links=True, use_headings=True)


def find_differentiator(pages):
    return find_by_regex(pages, DIFFERENTIATOR_RE, prefer=("home", "about", "product"))


def find_faq(pages):
    for p in pages:
        for n, _ in doc_top_nodes(p.doc):
            if "FAQPage" in node_types(n):
                return _found("FAQPage JSON-LD (%d questions)" % len(_walk_key(n, "mainEntity")), p, "jsonld:FAQPage")
    for p in pages:
        for h in p.doc.headings:
            if FAQ_HEADING_RE.search(h["text"] or ""):
                return _found(h["text"], p, "heading")
        qs = [h["text"] for h in _headings(p, 2, 4) if (h["text"] or "").rstrip().endswith("?")]
        if len(qs) >= 3:
            return _found("; ".join(qs[:3]), p, "heading:questions")
    return None


def brand_name(pages, site=None):
    """{"value","source","page"} for the brand: JSON-LD org/person name, og:site_name, repeated title segment, host."""
    for p in _ordered(pages, ("home", "about")):
        for n, _ in doc_top_nodes(p.doc):
            if is_org_node(n, allow_person=True) and _present(n.get("name")) and isinstance(n.get("name"), str):
                return _found(n["name"], p, "jsonld:%s.name" % node_types(n)[0])
    for p in _ordered(pages, ("home",)):
        sn = p.doc.meta("og:site_name", "application-name")
        if sn:
            return _found(sn, p, "meta:og:site_name")
    segs = {}
    for p in pages:
        for seg in re.split(r"\s+[|—–-]\s+|\s*:\s+", p.doc.title or ""):
            seg = seg.strip()
            if 1 <= len(seg.split()) <= 4:
                segs[seg] = segs.get(seg, 0) + 1
    common = [s for s, c in sorted(segs.items(), key=lambda x: -x[1]) if c >= 2]
    if common:
        return {"value": common[0], "page": None, "source": "title:common_segment"}
    host = (urlsplit(site or (pages[0].final_url if pages else "")).hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    name = host.split(".")[0] if host else None
    return {"value": name.capitalize() if name else None, "page": None, "source": "host"}
