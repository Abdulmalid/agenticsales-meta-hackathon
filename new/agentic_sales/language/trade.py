"""Shop talk: what customers mean by the words of a trade.

A gadget buyer asks for "128 ROM, UK used, Face ID working, LLA"; a builder asks for "a trip of granite"; a hair buyer wants "12 inches, HD
lace frontal". A rep that does not know these words asks silly questions or, worse, answers the wrong thing. This is a small glossary per
line of business, picked from the shop's industry, its product names and the customer's own message, and put in the rep's instructions as
*meaning only*: it explains what the customer is asking, it is never a fact about what this shop sells. A condition, region, lock status or
quality grade is stated for a unit only when that unit's listing says so; otherwise the rep says it will confirm.

The owner can add their own words in Settings (`trade_terms`), which are listed with the same rule.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..security.untrusted import clean

MAX_TRADES = 2                 # the shop's own line of business plus at most one more the customer's message points to
MAX_OWNER_TERMS = 40
MAX_CHARS = 3600               # the whole section, so it never crowds out the product list


@dataclass(frozen=True)
class Trade:
    key: str
    label: str
    shop: re.Pattern            # matched against the shop's industry and product names
    talk: re.Pattern            # matched against the customer's message
    terms: tuple[tuple[str, str], ...]


def _p(words: str) -> re.Pattern:
    return re.compile(rf"(?i)\b(?:{words})\b")


TRADES: tuple[Trade, ...] = (
    Trade("gadgets", "phones, laptops and gadgets",
          _p(r"phones?|iphones?|samsung|tecno|infinix|itel|pixel|gadgets?|laptops?|macbooks?|ipads?|tablets?|airpods?|earbuds?|smart ?watch(?:es)?|consoles?|ps[45]|computers?|electronics?|accessor(?:y|ies)"),
          _p(r"rom|ram|face ?id|true ?tone|uk used|us used|lla|ll/a|zp/a|zpa|battery health|bh|icloud|esn|imei|swap|factory unlocked|network locked|jk|r-?sim|e-?sim|dual sim|open box|cpo|refurbished|ssd|hdd|core i[3579]|gen\b"),
          (("ROM / storage", "In Nigerian shop talk ROM is the storage (\"128 ROM\" = 128GB storage) and RAM is the memory. Both are asked together, like \"6/128\"."),
           ("new / sealed / brand new", "Never used, in its sealed box. Not the same as open box (box opened, barely used) or CPO / refurbished (restored and resold)."),
           ("UK used / US used / Nigerian used / fairly used / tokunbo", "Second-hand. UK used and US used were imported from there, Nigerian used was owned here, tokunbo means foreign used. Price falls in that order."),
           ("LLA, LL/A, ZP/A, J/A, B/A, CH/A, KH/A", "The letters at the end of an iPhone model number show the market it was made for: LL/A = USA, ZP/A = Hong Kong, J/A = Japan, B/A = UK, CH/A = China, KH/A = Korea. LLA is the one most asked for. They differ in SIM tray, network bands and FaceTime support."),
           ("Face ID working / not working", "Whether the iPhone's face unlock works. A phone whose screen or camera was changed often loses it, and customers ask because it hurts resale value. Do not say it works unless the listing says so."),
           ("True Tone", "A display feature that is often lost when a screen is replaced. Customers use it to check whether the screen is original."),
           ("battery health / BH", "The battery's remaining capacity as a percentage in Settings (\"BH 89%\"). Higher is better. Below about 80% usually means a battery change soon."),
           ("original screen / screen changed / aftermarket", "Whether the screen has been replaced. \"Changed\" or \"aftermarket\" is a copy part and lowers the value."),
           ("factory unlocked / network locked / iCloud locked / JK", "Factory unlocked works with any SIM. Network (carrier) locked works only on one network, sometimes with an R-SIM or JK chip. iCloud locked is tied to someone else's account and cannot be used until released: a serious problem."),
           ("dual SIM / eSIM", "Two physical SIMs, or a built-in digital SIM. Many US-market iPhones are eSIM only."),
           ("swap / trade-in", "The customer gives their old phone and pays the difference for another. The old phone's value is set only after it is checked."),
           ("IMEI", "The phone's unique serial number, dialled with *#06#. Customers ask for it to check the phone is not blacklisted."),
           ("SSD / HDD, i5 8th gen", "SSD is fast storage and HDD is slow, older storage. \"Core i5 8th gen\" names the processor and its generation; higher generation is newer."),
           ("complete accessories", "The box, charger and cable that came with it.")),
          ),
    Trade("fashion", "fashion, shoes and bags",
          _p(r"fashion|clothes|clothing|wears?|shoes?|sneakers?|footwear|bags?|ankara|fabrics?|lace|native|tailor(?:ing)?|boutique|thrift|jewell?ery|apparel"),
          _p(r"okrika|bend ?down|first copy|1st copy|a-?grade|aso ?ebi|senator|agbada|ankara|adire|corporate|made to order|custom(?:ised|ized)?|eu \d\d|uk \d\d?|us \d\d?|fits?"),
          (("size (UK / EU / US)", "Shoe and clothing sizes differ by system, so \"size 42\" is EU and \"size 8\" is usually UK or US. Ask which system when it is unclear, and confirm only the sizes listed."),
           ("okrika / bend down select / tokunbo / thrift", "Second-hand clothes, shoes or bags, often imported in bales."),
           ("first copy / A-grade / original", "A first copy or A-grade item is a close imitation, not the original brand. Say an item is original only when the listing says so."),
           ("Ankara, lace, George, Adire", "Fabrics and prints sold by the yard or in a 6-yard bundle, often bought to be sewn."),
           ("aso ebi", "Matching fabric a group buys to wear together at an event, so quantity and delivery date matter."),
           ("senator, agbada, native, English wear, corporate", "Styles of men's wear: senator is a plain two-piece native, agbada the large flowing robe set, English wear and corporate are suits and shirts."),
           ("made to order / custom", "Sewn or made after the customer pays, so it has a lead time and measurements are needed.")),
          ),
    Trade("beauty", "hair, beauty and skincare",
          _p(r"hair|wigs?|beauty|cosmetics?|skin ?care|makeup|perfumes?|fragrances?|salon|lashes|braids?|extensions?"),
          _p(r"frontal|closure|bundles?|bone straight|raw hair|brazilian|peruvian|hd lace|transparent lace|density|inches|inch|wig cap|install(?:ation)?|nafdac|original|fake"),
          (("bundles, closure, frontal", "Bundles are wefts of hair sold by weight and length, and a closure or frontal is the lace piece that finishes the hairline. A frontal covers ear to ear and a closure a smaller part."),
           ("raw hair / virgin hair / Brazilian / Peruvian / Vietnamese", "Grades and origins of human hair. Raw is the least processed and costs most. Do not claim a grade the listing does not give."),
           ("HD lace / transparent lace", "A thin lace that melts into the scalp for a natural hairline. HD is the finest."),
           ("12 inches, 14 inches", "The hair's length, 12 inches being short and 30 or more very long. Longer costs more."),
           ("density (150%, 180%)", "How full the wig is. Higher density is fuller and heavier."),
           ("bone straight", "A very straight, sleek style."),
           ("installation", "Fitting the wig, usually by a stylist, and often charged separately."),
           ("NAFDAC number", "The regulator's registration number on food, drugs and cosmetics. Do not claim a product is NAFDAC registered unless the listing says so.")),
          ),
    Trade("food", "food, groceries and provisions",
          _p(r"food|foodstuffs?|groceries|grocery|provisions?|rice|beans|garri|oil|fruits?|vegetables?|bakery|cakes?|catering|snacks?|drinks?|restaurant|kitchen|spices?|meat|fish"),
          _p(r"paint|derica|congo|mudu|olonka|tuber|bunch|crate|keg|carton|bag of|tray|per plate|pack|small chops|party|jollof"),
          (("paint / bucket", "A paint-bucket measure of grain such as rice or beans. The size differs from market to market, so confirm it when the listing does not say."),
           ("derica / congo / mudu / olonka", "Small tin or cup measures used to sell grain, garri or beans by volume. Their sizes vary by market."),
           ("bag, half bag, 50kg", "A bag of rice or beans is usually 50kg; a half bag is half of that."),
           ("keg", "A plastic container, often 25 litres, used for palm or groundnut oil."),
           ("tuber, bunch, basket, crate", "Yams are sold by the tuber, plantain or bananas by the bunch, tomatoes and peppers by the basket, eggs by the crate of 30."),
           ("small chops, party tray, per plate", "Catering is priced per plate or per tray and needs a date, a headcount and a delivery address."),
           ("NAFDAC", "The regulator's registration number on packaged food. Claim it only when the listing does.")),
          ),
    Trade("building", "building materials and hardware",
          _p(r"building|construction|cement|granite|sand|iron ?rods?|roofing|tiles?|hardware|plumbing|paints?|timber|planks?|pop|doors?"),
          _p(r"trip|tipper|tonne?s?|ton|granite|rod|12mm|16mm|gauge|long ?span|stone ?coated|sqm|carton|2 ?x ?4|bundle|pop"),
          (("trip / tipper / truck load", "Sand and granite are sold by the trip, meaning a truckload. The size of the truck (tipper) decides the price and quantity."),
           ("12mm, 16mm iron rod", "The thickness of a reinforcement rod. A bundle is a fixed count of rods, so confirm the count."),
           ("roofing sheet, long span, stone coated", "Metal sheets sold by length and thickness (for example 0.45mm or 0.55mm; thicker costs more). Stone coated tiles are heavier and costlier."),
           ("tiles per carton / sqm", "Floor and wall tiles are priced per carton, and each carton covers a set area in square metres."),
           ("bag of cement", "A 50kg bag. Brand and the day's price change often."),
           ("POP", "Plaster of Paris, used for ceilings and mouldings."),
           ("2 by 4 timber", "A standard plank size, sold by the piece and the length.")),
          ),
    Trade("auto", "cars and auto parts",
          _p(r"cars?|autos?|automobiles?|vehicles?|motors?|spare ?parts?|tyres?|tires?|engine|toyota|lexus|honda|mercedes"),
          _p(r"tokunbo|nigerian used|foreign used|belgium|duty|customs|registered|full option|first body|clean title|accident|mileage|oem|taiwan|japan|auto|manual|keke|okada"),
          (("tokunbo / foreign used", "A car or part that was used abroad and then imported. Nigerian used was owned here."),
           ("customs duty paid", "Whether import duty has been paid on the car, which decides whether it can be registered. Never claim it unless the listing says so."),
           ("registered (Lagos / Abuja / unregistered)", "Whether the car has plate numbers and in which state."),
           ("full option", "Loaded with the maker's extras such as leather seats, sunroof, cameras and navigation."),
           ("first body", "The original paint and panels, never repainted or repaired after an accident."),
           ("auto / manual", "Automatic or manual gearbox."),
           ("OEM / Taiwan / Japan / China parts", "OEM is the maker's own part. Others are copies made in those places and usually cost less and last less."),
           ("mileage", "The distance driven. Lower is usually better but the figure can be altered, so only quote it from the listing.")),
          ),
    Trade("home", "furniture, appliances and power",
          _p(r"furniture|appliances?|home|kitchen|fridge|freezers?|air ?conditioners?|ac\b|generators?|inverters?|solar|panels?|batter(?:y|ies)|fans?|cookers?|tv|television|sofa"),
          _p(r"hp|btu|inverter|kva|kw|watts?|tubular|lithium|split unit|standing|gas cooker|burner|foam|sofa|3 ?-? ?2 ?-? ?1|l-?shaped|volts?|amps?|ah\b"),
          (("1HP, 1.5HP, 2HP (air conditioner)", "The cooling power of an AC. Bigger rooms need more; a small bedroom is usually 1HP or 1.5HP."),
           ("split unit / window unit / standing", "A split AC has an indoor and an outdoor part; a window unit is one box; standing is a floor-standing model."),
           ("inverter AC", "An AC that varies its speed and uses less power, which matters where power is costly."),
           ("KVA (inverter or generator)", "The size of the power unit. A 3.5KVA inverter runs a few lights, TV, fans and a fridge; bigger loads need more."),
           ("lithium / tubular battery", "Lithium batteries are lighter, last longer and cost more. Tubular batteries are the older, cheaper type."),
           ("solar panel watts", "The panel's power rating (for example 200W). More watts gives more charge."),
           ("3-2-1 sofa", "A sofa set of one three-seater, one two-seater and one single seat."),
           ("UK used appliance", "A second-hand appliance imported from the UK, normally cheaper than new.")),
          ),
    Trade("property", "land and property",
          _p(r"land|plots?|estates?|property|properties|real estate|houses?|apartments?|rent|flats?"),
          _p(r"c of o|survey|deed|assignment|governor'?s consent|off ?plan|carcass|sqm|plot|service charge|gazette|excision|title"),
          (("C of O, Governor's consent, deed of assignment", "Title documents. A C of O is the state's certificate of occupancy; consent is the governor's approval of a transfer; a deed of assignment records a sale. Never claim a title unless the listing states it."),
           ("survey plan", "A drawn map of the land's boundaries by a licensed surveyor."),
           ("plot / sqm", "A plot is a standard parcel (commonly about 600 sqm in Lagos, but it varies); sqm is square metres."),
           ("off plan / carcass / finished", "Off plan is sold before it is built, carcass is the bare building without finishing, finished is ready to live in."),
           ("service charge", "A yearly fee in an estate for security, cleaning and power.")),
          ),
)

COMMON: tuple[tuple[str, str], ...] = (
    ("last price / final price", "The lowest price the customer hopes to hear. Answer with the price you can actually confirm, not a vague \"come down small\"."),
    ("balance (as in \"balance me\")", "Customers sometimes ask you to reduce the price a little. It does not mean the money they still owe."),
    ("POD / pay on delivery", "Paying when the goods arrive. Say the shop offers it only if the shop's payment terms say so."),
    ("waybill / park", "Sending goods by a transport company to a motor park in another city, where the customer collects them."),
)


def _owner_terms(terms: dict | None) -> list[tuple[str, str]]:
    out = []
    for k, v in list((terms or {}).items())[:MAX_OWNER_TERMS]:
        term, meaning = " ".join(clean(str(k)).split())[:40], " ".join(clean(str(v)).split())[:200]
        if term and meaning:
            out.append((term, meaning))
    return out


def pick(industry: str, product_names: list[str], message: str = "") -> list[Trade]:
    """The lines of business this shop and this message belong to, the shop's own first."""
    shop_text = " ".join([industry, *product_names])
    scored = []
    for t in TRADES:
        shop, talk = len(t.shop.findall(shop_text)), len(t.talk.findall(message or ""))
        if shop or talk >= 2:
            scored.append((shop > 0, shop + talk, t))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [t for _, _, t in scored[:MAX_TRADES]]


def trade_context(industry: str, product_names: list[str], message: str = "", owner_terms: dict | None = None) -> str:
    """The section of the rep's instructions that explains the shop talk, or an empty string when there is nothing to say."""
    lines = []
    mine = _owner_terms(owner_terms)
    if mine:
        lines += ["this shop's own words:", *[f"- {term}: {meaning}" for term, meaning in mine]]
    for t in pick(industry, product_names, message):
        lines += [f"{t.label}:", *[f"- {term}: {meaning}" for term, meaning in t.terms]]
    lines += ["everyday selling words:", *[f"- {term}: {meaning}" for term, meaning in COMMON]]
    text = "\n".join(lines)
    if len(text) > MAX_CHARS:                               # drop whole terms from the end, never half a line
        text = text[:MAX_CHARS].rsplit("\n", 1)[0]
    return text
