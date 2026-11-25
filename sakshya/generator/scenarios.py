from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sakshya.core.geo import offset_point
from sakshya.generator.builder import Builder, Pending, ist
from sakshya.generator.world import DEVANAGARI, FIRST_NAMES, Atm, Person, Tower, World
from sakshya.generator.writer import CaseWriter, RowRef, json_text

LURE_LINES = [
    "Namaste ji, main TradeX Prime se bol raha hoon. Hamare premium trading group mein aapko free entry mil rahi hai.",
    "Hamare members ko har mahine 25 se 30 percent guaranteed returns milte hain, bilkul safe hai.",
    "Company SEBI registered hai, certificate aapko email par bhej diya hai.",
    "Aap app download kijiye aur pehle chhota deposit karke profit dekhiye.",
    "Sir/Madam aaj special slot khula hai, jitna zyada invest karenge utna zyada profit.",
    "Withdrawal ke liye pehle tax aur service charge deposit karna hoga, phir pura amount account mein aa jayega.",
]
VICTIM_REPLIES = [
    "Theek hai, details bhejiye.",
    "Kya yeh sach mein safe hai?",
    "Maine app install kar liya hai.",
    "Payment kis UPI ID par karna hai?",
    "Mera profit withdraw nahi ho raha, kya problem hai?",
    "Aap phone kyon nahi utha rahe?",
]
THREAT_LINES = [
    "Aapka video humare paas record hai. Agar paise nahi bheje to aapke sab contacts aur family ko bhej denge.",
    "2 ghante mein 50000 bhejo warna video viral kar dunga, YouTube aur Facebook par daal dunga.",
    "Police ke paas jaoge to aur problem hogi. Chup chaap payment karo.",
    "Aakhri warning hai, abhi payment karo nahi to sabko share kar dunga.",
]
BENIGN_LINES = [
    "Sir aapka sofa set order ho gaya hai, delivery 5 din mein ho jayegi.",
    "Factory se maal late aa raha hai, thoda time lagega.",
    "Delivery van kal aayegi, address confirm kar dijiye.",
    "Sorry ji, transport strike ki wajah se delay ho gaya.",
]


@dataclass
class Chain:
    l1: list[str]
    l2: list[str]
    cash_account: str
    cash_atm: Atm
    cash_times: list[datetime] = field(default_factory=list)
    withdrawals: list[dict] = field(default_factory=list)
    tainted_accounts: list[str] = field(default_factory=list)
    unknown_destinations: list[str] = field(default_factory=list)
    layering_refs: list[Pending] = field(default_factory=list)
    payment_refs: list[Pending] = field(default_factory=list)
    victim_total: float = 0.0
    cash_total: float = 0.0


def inr(amount: float) -> str:
    whole = f"{int(round(amount))}"
    if len(whole) <= 3:
        return whole
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups) + "," + tail


def _date(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d")


def _hindi(name: str) -> str:
    return DEVANAGARI.get(name, name)


def victim_background(b: Builder, victim: Person, account: str, days: int = 50) -> None:
    w = b.w
    employer = w.rng.choice(["Acme Infotech Pvt Ltd", "Bluegrain Foods Ltd", "Northfield Logistics"])
    for month in range(2):
        b.external_credit(
            account, float(w.rng.choice([68000, 82000, 95000, 112000])), w.at(-days + 5 + month * 30, 9, 30), employer, "SALARY"
        )
        b.external_debit(account, 22000.0, w.at(-days + 7 + month * 30, 10, 15), "Landlord rent", "RENT", channel="IMPS")
    for _ in range(int(days * 0.6)):
        day = -w.rng.randint(1, days)
        b.external_debit(
            account,
            float(w.rng.randint(180, 4200)),
            w.at(day, w.rng.randint(9, 21), w.rng.randint(0, 59)),
            w.rng.choice(["Fresh Mart", "City Pharmacy", "Metro Fuel", "Book Corner", "Spice Kitchen"]),
            "POS",
            channel=w.rng.choice(["POS", "UPI"]),
        )


def victim_phone_background(b: Builder, victim_tuple: tuple[str, str, str, Tower], days: int = 60) -> None:
    w = b.w
    contacts = [(w.phone(), w.imei(), w.imsi(), w.home_tower(victim_tuple[3].hub)) for _ in range(5)]
    for _ in range(48):
        contact = w.rng.choice(contacts)
        moment = w.at(-w.rng.randint(0, days), w.rng.randint(8, 22), w.rng.randint(0, 59), w.rng.randint(0, 59))
        if w.rng.random() < 0.5:
            b.call(victim_tuple, contact, moment, w.rng.randint(20, 900))
        else:
            b.call(contact, victim_tuple, moment, w.rng.randint(20, 900))
    for _ in range(10):
        moment = w.at(-w.rng.randint(0, days), w.rng.randint(8, 22), w.rng.randint(0, 59))
        b.sms_to_victim(
            moment,
            w.rng.choice(["VK-DELIVR", "AD-OFFERS", "JM-HEALTH"]),
            w.rng.choice(
                ["Your order is out for delivery.", "Flat 20 percent off this weekend.", "Your appointment is confirmed."]
            ),
        )


def debit_alert(b: Builder, account: str, amount: float, moment: datetime, upi: str, ref: str) -> RowRef | None:
    tail = account.split(":")[1][-4:]
    code = account[:4]
    sender = {"IVBK": "IV-IVBANK", "NCBK": "NC-NCBANK", "GGBK": "GG-GGBANK", "CUBK": "CU-CUBANK"}.get(code, "BK-ALERTS")
    body = (
        f"Rs.{amount:.2f} debited from A/c XX{tail} on {moment.strftime('%d-%m-%y')} to VPA {upi} "
        f"(UPI Ref No {ref}). Not you? Call 1800 000 1111 - {code[:3]}"
    )
    return b.sms_to_victim(moment + timedelta(seconds=b.w.rng.randint(3, 12)), sender, body)


def money_chain(
    b: Builder,
    victim_account: str,
    mule_l1: str,
    l2_accounts: list[str],
    cash_account: str,
    cash_atm: Atm,
    payments: list[tuple[datetime, float]],
    unknown_dest: dict[str, str],
    alert: bool,
    commission: float,
) -> Chain:
    w = b.w
    chain = Chain(l1=[mule_l1], l2=l2_accounts, cash_account=cash_account, cash_atm=cash_atm)
    total = 0.0
    for moment, amount in payments:
        debit, _, ref = b.transfer(victim_account, mule_l1, amount, moment, "UPI", "Investment deposit")
        chain.payment_refs.append(debit)
        b.truth["events"].append({"phase": "payment", "time": moment.timestamp(), "ref": debit})
        total += amount
        if alert:
            sms_ref = debit_alert(b, victim_account, amount, moment, b.account_info[mule_l1]["upi"], ref)
            if sms_ref is not None:
                b.pending_truth.append(("same_event", (debit, sms_ref)))
    chain.victim_total = total
    keep = round(total * commission / 100.0 / 100.0) * 100.0
    forward = total - keep
    start = payments[-1][0] + timedelta(minutes=w.rng.randint(4, 11))
    shares = [w.rng.uniform(0.6, 1.4) for _ in l2_accounts]
    remaining = forward
    for index, account in enumerate(l2_accounts):
        amount = remaining if index == len(l2_accounts) - 1 else round(forward * shares[index] / sum(shares) / 1000.0) * 1000.0
        remaining -= amount
        moment = start + timedelta(minutes=index * w.rng.randint(2, 5), seconds=w.rng.randint(0, 50))
        debit, _, _ = b.transfer(mule_l1, account, amount, moment, "IMPS", "Business payment")
        chain.layering_refs.append(debit)
        b.truth["events"].append({"phase": "layering", "time": moment.timestamp(), "ref": debit})
        if account == cash_account:
            cash_start = moment + timedelta(minutes=w.rng.randint(55, 95))
            cash_left = amount - w.rng.randint(15, 40) * 1000.0
            withdrawn = 0.0
            step = 0
            moment_cash = cash_start
            while withdrawn + 10000 <= cash_left and step < 5:
                piece = float(min(49500.0, cash_left - withdrawn))
                piece = max(10000.0, round(piece / 500.0) * 500.0)
                result = b.withdraw(account, cash_atm, piece, moment_cash, frame=True)
                chain.withdrawals.append(result)
                chain.cash_times.append(moment_cash)
                b.truth["events"].append({"phase": "cash_out", "time": moment_cash.timestamp(), "ref": result["journal"]})
                withdrawn += piece
                step += 1
                moment_cash += timedelta(seconds=w.rng.randint(70, 140))
            chain.cash_total = withdrawn
        else:
            dest = unknown_dest[account]
            hop = moment + timedelta(minutes=w.rng.randint(20, 55))
            onward = amount - w.rng.randint(2, 12) * 1000.0
            b.transfer(account, dest, onward, hop, "IMPS", "Supplier payment")
            chain.unknown_destinations.append(dest)
    chain.tainted_accounts = [mule_l1, *l2_accounts, *chain.unknown_destinations]
    return chain


def atm_background(b: Builder, atm: Atm, day: int, count: int) -> None:
    w = b.w
    for _ in range(count):
        moment = w.at(day, w.rng.randint(8, 21), w.rng.randint(0, 59), w.rng.randint(0, 59))
        b.withdraw(
            None,
            atm,
            float(w.rng.choice([500, 1000, 2000, 2500, 3000, 5000, 10000])),
            moment,
            masked=str(w.rng.randint(1000, 9999)),
            frame=False,
        )


def presence_series(
    b: Builder, msisdn: str, imei: str, imsi: str, start: datetime, end: datetime, tower: Tower, every_s: int, partner: str
) -> list[RowRef]:
    refs = []
    moment = start
    while moment <= end:
        ref = b.cdr_row(msisdn, moment, partner, "DATA", b.w.rng.randint(30, 240), imei, imsi, tower)
        if ref:
            refs.append(ref)
        moment += timedelta(seconds=every_s + b.w.rng.randint(-every_s // 4, every_s // 4))
    return refs


@dataclass
class UpiParams:
    fixed: bool = True
    n_payments: int = 3
    n_l2: int = 2
    decoys: bool = True
    utc_export: bool = True
    dvr_offset_s: float = 420.0
    background: int = 320
    network: bool = True
    cloud: bool = True


def build_upi(world: World, writer: CaseWriter, p: UpiParams) -> None:
    w = world
    b = Builder(w, writer)
    rng = w.rng
    ivb = w.bank_by_code("IVBK")
    victim = w.person("victim", "DWK", "Meera Iyer" if p.fixed else w.name())
    suspect = w.person("suspect", "NOI", "Ankit Chauhan" if p.fixed else w.name())
    decoy_base = "Rohit Kumar" if p.fixed else f"{rng.choice(FIRST_NAMES)} Kumar"
    lurer_alias = "Sunil Verma" if p.fixed else w.name()
    vn = w.give_phone(victim)
    v_imei = w.give_handset(victim)
    va = w.give_account(victim, ivb, handle=victim.name.lower().replace(" ", "."))
    victim.emails.append(f"{victim.name.lower().replace(' ', '.')}@mail.test")
    l1 = w.give_phone(suspect, kyc_name=lurer_alias, kyc_address=w.address("JMT"))
    s2 = w.give_phone(suspect, kyc_name=_hindi(decoy_base), kyc_address=suspect.address)
    h1 = w.give_handset(suspect)
    h2 = w.give_handset(suspect)
    laptop_mac = "3c:52:82:" + ":".join(f"{rng.randint(0, 255):02x}" for _ in range(3))
    router_mac = "c4:6e:1f:" + ":".join(f"{rng.randint(0, 255):02x}" for _ in range(3))
    phone_mac = "a4:50:46:" + ":".join(f"{rng.randint(0, 255):02x}" for _ in range(3))
    hostname = f"DESKTOP-{rng.randint(1000, 9999)}{rng.choice('ABCDEFGHJK')}"
    cloud_account = f"{suspect.name.split()[0].lower()}.{rng.randint(10, 99)}@mail.test"
    home = w.home_tower("NOI")
    home_lat, home_lon = offset_point(home.lat, home.lon, rng.uniform(-300, 300), rng.uniform(-300, 300))
    mule_a = w.person("mule_a", "JMT", "Amit Yadav" if p.fixed else w.name())
    pa = w.give_phone(mule_a)
    a_account = w.give_account(mule_a, ivb, handle="tradex.support")
    atm_x = w.atm_in("NOI")
    cash_bank = w.bank_by_code(atm_x.bank)
    decoy_b = w.person("mule_b", "PAT", f"{decoy_base} Sharma")
    pb = w.give_phone(decoy_b)
    pb_imei = w.give_handset(decoy_b)
    mule_c = w.person("mule_c", "LKO", "Pooja Singh" if p.fixed else w.name())
    pc = w.give_phone(mule_c)
    l2_people = [decoy_b, mule_c]
    for index in range(max(0, p.n_l2 - 2)):
        extra = w.person(f"mule_e{index}", rng.choice(["LKO", "PAT", "JMT"]))
        w.give_phone(extra)
        l2_people.append(extra)
    if p.n_l2 == 1:
        l2_people = [mule_c]
    for person in l2_people:
        bank = cash_bank if person is mule_c else w.bank(exclude="IVBK")
        w.give_account(person, bank, handle=None)
    c_account = mule_c.accounts[0]
    decoy_d2 = w.person("decoy_d2", "LXN", decoy_base)
    pd2 = w.give_phone(decoy_d2)
    d2_account = w.give_account(decoy_d2, w.bank_by_code("GGBK"), handle=decoy_base.split()[0].lower() + "k")
    unknown_people = {}
    for person in l2_people:
        if person is not mule_c:
            dest = w.person(f"dest_{person.key}", rng.choice(["JMT", "PAT"]))
            w.give_account(dest, w.bank())
            unknown_people[person.accounts[0]] = dest
    for person, account in [(victim, va), (mule_a, a_account), (decoy_d2, d2_account)]:
        b.register_account(account, person, b.w.bank_by_code(account[:4]))
    for person in l2_people:
        b.register_account(person.accounts[0], person, w.bank_by_code(person.accounts[0][:4]))
    for dest in unknown_people.values():
        b.register_account(dest.accounts[0], dest, w.bank_by_code(dest.accounts[0][:4]))
    b.open_statement(va, float(rng.randint(420, 640) * 1000))
    b.open_statement(a_account, 0.0)
    for person in l2_people:
        b.open_statement(person.accounts[0], float(rng.randint(2, 40) * 1000) if person is not mule_c else 500.0)

    victim_background(b, victim, va)
    if p.decoys:
        b.transfer(va, d2_account, 18000.0, w.at(-55, 16, 20), "UPI", "Furniture")
    b.external_credit(a_account, 1.0, w.at(-19, 12, 5), "Account verification", "VERIFY", channel="IMPS")
    b.external_credit(c_account, 500.0, w.at(-11, 13, 40), "Cash deposit", "CDM", channel="CASH")
    if decoy_b in l2_people:
        for _ in range(14):
            day = -rng.randint(1, 80)
            if rng.random() < 0.5:
                b.external_credit(
                    decoy_b.accounts[0],
                    float(rng.randint(2, 18) * 500),
                    w.at(day, rng.randint(9, 20), rng.randint(0, 59)),
                    "Customer",
                    "UPI",
                    channel="UPI",
                )
            else:
                b.external_debit(
                    decoy_b.accounts[0],
                    float(rng.randint(2, 14) * 500),
                    w.at(day, rng.randint(9, 20), rng.randint(0, 59)),
                    "Wholesale Traders",
                    "UPI",
                    channel="UPI",
                )

    for msisdn in (l1, s2, pb):
        b.cdr(msisdn)
    victim_tuple = (vn, v_imei, victim.imsis[vn], w.home_tower("DWK"))
    l1_tuple = (l1, h1, suspect.imsis[l1], home)
    b.victim_device(vn, p.utc_export)
    victim_phone_background(b, victim_tuple)

    contact_day = -rng.randint(3, 5)
    t_contact = w.at(contact_day, 10, rng.randint(5, 40))
    other_label = l1[:3] + " " + l1[3:8] + " " + l1[8:]
    b.chat(l1, victim.name.split()[0], other_label)
    b.say(l1, t_contact, False, LURE_LINES[0], tag="first_contact")
    b.say(l1, t_contact + timedelta(minutes=6), True, VICTIM_REPLIES[0])
    b.say(l1, t_contact + timedelta(minutes=9), False, LURE_LINES[1])
    b.say(l1, t_contact + timedelta(minutes=15), True, VICTIM_REPLIES[1])
    b.say(l1, t_contact + timedelta(minutes=18), False, LURE_LINES[2])
    t_email = w.at(contact_day + 1, 11, rng.randint(10, 50))
    b.say(l1, t_email + timedelta(hours=2), False, LURE_LINES[3])
    b.say(l1, t_email + timedelta(hours=3), True, VICTIM_REPLIES[2])
    b.call(l1_tuple, victim_tuple, w.at(contact_day + 1, 18, rng.randint(0, 50), rng.randint(0, 59)), rng.randint(180, 320))
    b.call(l1_tuple, victim_tuple, w.at(-1, 12, rng.randint(0, 50), rng.randint(0, 59)), rng.randint(90, 200))
    t_pay = w.at(0, 13, rng.randint(30, 55))
    b.say(l1, t_pay - timedelta(minutes=25), False, LURE_LINES[4])
    b.say(l1, t_pay - timedelta(minutes=20), True, VICTIM_REPLIES[3])
    b.say(l1, t_pay - timedelta(minutes=18), False, f"Is UPI ID par payment kijiye: {mule_a.upis[a_account]}")
    b.truth["events"].append({"phase": "contact", "time": t_contact.timestamp(), "tag": "first_contact"})

    scam_domain = "tradexprime.test"
    b.email(
        "lure_offer.eml",
        ("TradeX Prime Support", f"support@{scam_domain}"),
        (victim.name, victim.emails[0]),
        t_email,
        "Welcome to TradeX Prime: SEBI registered trading desk",
        "Dear Investor,\n\nGreetings from TradeX Prime. "
        "We are a SEBI registered trading desk offering guaranteed monthly returns of 25 to 30 percent.\n"
        "Register on our app and start with a small deposit to see your profit:\n"
        f"https://{scam_domain}/app/register?ref={rng.randint(1000, 9999)}\n\nYour relationship manager will call you today.\n\n"
        "Regards,\nTradeX Prime Investor Desk",
        "198.51.100.77",
    )
    b.truth["events"].append({"phase": "lure", "time": t_email.timestamp(), "ref": RowRef("email/lure_offer.eml", 0)})

    amounts = []
    total_target = rng.randint(22, 34) * 10000
    for _ in range(p.n_payments):
        share = total_target // p.n_payments
        amounts.append(float(min(100000, max(30000, round(share * rng.uniform(0.8, 1.2) / 1000) * 1000))))
    payments = []
    moment = t_pay
    for amount in amounts:
        payments.append((moment, amount))
        moment += timedelta(minutes=rng.randint(7, 19), seconds=rng.randint(0, 59))
    unknown_dest = {acct: person.accounts[0] for acct, person in unknown_people.items()}
    tamper_index = 2 if p.fixed else rng.randint(1, 3)
    b.enable_cctv(atm_x, p.dvr_offset_s, tamper_index=tamper_index)
    chain = money_chain(
        b,
        va,
        a_account,
        [person.accounts[0] for person in l2_people],
        c_account,
        atm_x,
        payments,
        unknown_dest,
        alert=True,
        commission=rng.uniform(1.0, 3.0),
    )
    b.say(l1, payments[-1][0] + timedelta(hours=3), True, VICTIM_REPLIES[4])
    b.say(l1, payments[-1][0] + timedelta(hours=5), False, LURE_LINES[5])
    b.say(l1, payments[-1][0] + timedelta(hours=26), True, VICTIM_REPLIES[5])
    b.email(
        "deposit_receipt.eml",
        ("TradeX Prime Payments", f"payments@{scam_domain}"),
        (victim.name, victim.emails[0]),
        payments[-1][0] + timedelta(minutes=40),
        "Deposit received: profit credited to your wallet",
        f"Dear Investor,\n\nWe have received your deposit of Rs {inr(chain.victim_total)}. Your wallet now shows a profit of "
        f"Rs {inr(chain.victim_total * 0.32)}.\nTo withdraw, pay the applicable tax and service charge via the app.\n\n"
        f"https://{scam_domain}/wallet\n\nTradeX Prime",
        "198.51.100.77",
    )
    atm_background(b, atm_x, 0, rng.randint(12, 18))

    for day in range(contact_day - 25, 0):
        for _ in range(rng.randint(1, 3)):
            b.cdr_row(
                l1,
                w.at(day, rng.randint(9, 21), rng.randint(0, 59), rng.randint(0, 59)),
                w.phone(),
                "VOICE-MO",
                rng.randint(20, 400),
                h1,
                suspect.imsis[l1],
                home,
            )
    recruit = w.at(-24, 15, rng.randint(0, 50))
    b.call(l1_tuple, (pa, w.imei(), mule_a.imsis[pa], w.home_tower("JMT")), recruit, rng.randint(240, 500))
    b.call(
        (pa, w.imei(), mule_a.imsis[pa], w.home_tower("JMT")),
        l1_tuple,
        recruit + timedelta(days=3, hours=2),
        rng.randint(60, 200),
    )
    b.call(
        l1_tuple, (pc, w.imei(), mule_c.imsis[pc], w.home_tower("LKO")), w.at(-13, 17, rng.randint(0, 50)), rng.randint(120, 400)
    )
    for day in (-3, -2, -1):
        b.cdr_row(s2, w.at(day, 9, rng.randint(0, 59)), w.phone(), "VOICE-MO", rng.randint(30, 300), h2, suspect.imsis[s2], home)
        presence_series(b, s2, h2, suspect.imsis[s2], w.at(day, 10, 0), w.at(day, 20, 0), home, 5400, "INTERNET")
    cash_first = chain.cash_times[0]
    near_atm = w.tower_near(atm_x.lat, atm_x.lon)
    presence_series(b, s2, h1, suspect.imsis[s2], w.at(0, 9, 0), cash_first - timedelta(minutes=50), home, 3600, "INTERNET")
    presence_series(
        b,
        s2,
        h1,
        suspect.imsis[s2],
        cash_first - timedelta(minutes=6),
        chain.cash_times[-1] + timedelta(minutes=5),
        near_atm,
        180,
        "INTERNET",
    )
    presence_series(
        b, s2, h1, suspect.imsis[s2], chain.cash_times[-1] + timedelta(minutes=55), w.at(0, 22, 0), home, 3600, "INTERNET"
    )
    patna = w.home_tower("PAT")
    pb_tuple = (pb, pb_imei, decoy_b.imsis[pb], patna)
    family = (w.phone(), w.imei(), w.imsi(), patna)
    for hour in (9, 11, 13, 15, 17, 19):
        b.call(pb_tuple, family, w.at(0, hour, rng.randint(0, 59)), rng.randint(40, 300))
    b.cdr_row(
        pb,
        cash_first + timedelta(minutes=rng.randint(-3, 3)),
        family[0],
        "VOICE-MO",
        rng.randint(60, 200),
        pb_imei,
        decoy_b.imsis[pb],
        patna,
    )

    window_start = cash_first - timedelta(minutes=30)
    window_end = cash_first + timedelta(minutes=25)
    b.background_dump(atm_x, window_start, window_end, int(p.background * w.scale))
    b.dump_row(atm_x, cash_first - timedelta(minutes=rng.randint(2, 9)), near_atm, s2, h1, suspect.imsis[s2])
    b.dump_row(atm_x, chain.cash_times[-1] + timedelta(minutes=rng.randint(1, 4)), near_atm, s2, h1, suspect.imsis[s2])

    if p.cloud:
        points = []
        for day in (-1, 0):
            moment = w.at(day, 8, 0)
            while moment < w.at(day, 23, 0):
                if day == 0 and cash_first - timedelta(minutes=35) <= moment <= chain.cash_times[-1] + timedelta(minutes=25):
                    moment += timedelta(minutes=12)
                    continue
                lat, lon = offset_point(home_lat, home_lon, rng.uniform(-60, 60), rng.uniform(-60, 60))
                points.append((moment, lat, lon, rng.choice([20, 35, 50])))
                moment += timedelta(minutes=rng.randint(10, 18))
        atm_points = []
        moment = cash_first - timedelta(minutes=4)
        while moment <= chain.cash_times[-1] + timedelta(minutes=4):
            lat, lon = offset_point(atm_x.lat, atm_x.lon, rng.uniform(-25, 25), rng.uniform(-25, 25))
            atm_points.append((moment, lat, lon, rng.choice([12, 18, 25])))
            moment += timedelta(minutes=rng.randint(3, 5))
        b.cloud(cloud_account, s2, points + atm_points)

    if p.network:
        lan_laptop, lan_phone = "192.168.1.23", "192.168.1.31"
        panel_ip, vpn_ip = "203.0.113.45", "198.51.100.77"
        first_beacon = None
        for day in range(contact_day, 1):
            moment = w.at(day, 10, rng.randint(0, 10))
            end = w.at(day, 19, 0)
            while moment < end:
                ref = b.net(
                    moment,
                    lan_laptop,
                    laptop_mac,
                    panel_ip,
                    443,
                    f"panel.{scam_domain}",
                    rng.randint(380, 720),
                    rng.randint(900, 2400),
                )
                first_beacon = first_beacon or (moment, ref)
                moment += timedelta(seconds=120 + rng.uniform(-5, 5))
            for _ in range(3):
                start = w.at(day, rng.randint(10, 18), rng.randint(0, 59))
                b.net(start, lan_laptop, laptop_mac, vpn_ip, 1194, "", rng.randint(20000, 400000), rng.randint(80000, 900000))
            for _ in range(60):
                moment = w.at(day, rng.randint(7, 23), rng.randint(0, 59), rng.randint(0, 59))
                host = rng.choice(
                    ["news.portal.test", "video.stream.test", "shop.market.test", "maps.service.test", "cdn.static.test"]
                )
                b.net(
                    moment,
                    lan_phone,
                    phone_mac,
                    f"192.0.2.{rng.randint(10, 200)}",
                    443,
                    host,
                    rng.randint(800, 9000),
                    rng.randint(9000, 900000),
                )
        b.truth["events"].append({"phase": "control", "time": first_beacon[0].timestamp(), "ref": first_beacon[1]})
        incident = {
            "tool": "UniAethel",
            "version": "1.0",
            "capture": {"file": "router_mirror.pcap", "start_utc": w.at(contact_day, 0, 0).astimezone().isoformat()},
            "incidents": [
                {
                    "id": "INC-001",
                    "host": lan_laptop,
                    "label": "C2",
                    "trajectory": "Stable",
                    "window": {"start": w.at(contact_day, 10, 0).isoformat(), "end": w.at(0, 19, 0).isoformat()},
                    "counterparty": {"top_destination": panel_ip, "distinct_destinations": 1},
                    "scores": {"C2": 0.71, "RECON": 0.08, "DDOS": 0.0, "EXFIL": 0.05},
                    "evidence_vector": {"A_M": 0.22, "A_IF": 0.41, "A_TCN": 0.97, "A_G": 0.93},
                    "reasons": [
                        "recurrence concentrated on a single destination (phi=1.00)",
                        "strong temporal recurrence to a previously unseen destination (phi=0.91)",
                        "communication structure changed (phi=0.93)",
                    ],
                }
            ],
        }
        b.cw.text("network/uniaethel_incidents.json", "uniaethel", raw_json=True).add(json_text(incident))
        b.seizure(
            [
                {
                    "item_id": "S-01",
                    "seized_time": w.at(9, 11, 20).strftime("%d.%m.%Y %H:%M"),
                    "premises": suspect.address,
                    "premises_lat": round(home_lat, 6),
                    "premises_lon": round(home_lon, 6),
                    "item_type": "laptop",
                    "description": "Black laptop, charger",
                    "imei": "",
                    "msisdn": "",
                    "imsi": "",
                    "mac": laptop_mac,
                    "hostname": hostname,
                    "officer": "SI R. Meena",
                },
                {
                    "item_id": "S-02",
                    "seized_time": w.at(9, 11, 25).strftime("%d.%m.%Y %H:%M"),
                    "premises": suspect.address,
                    "premises_lat": round(home_lat, 6),
                    "premises_lon": round(home_lon, 6),
                    "item_type": "mobile phone",
                    "description": "Android handset with one SIM",
                    "imei": h1,
                    "msisdn": s2,
                    "imsi": suspect.imsis[s2],
                    "mac": phone_mac,
                    "hostname": "",
                    "officer": "SI R. Meena",
                },
                {
                    "item_id": "S-03",
                    "seized_time": w.at(9, 11, 30).strftime("%d.%m.%Y %H:%M"),
                    "premises": suspect.address,
                    "premises_lat": round(home_lat, 6),
                    "premises_lon": round(home_lon, 6),
                    "item_type": "router",
                    "description": "Wi-Fi router, power adapter",
                    "imei": "",
                    "msisdn": "",
                    "imsi": "",
                    "mac": router_mac,
                    "hostname": "",
                    "officer": "SI R. Meena",
                },
            ]
        )

    subscribers = [
        (vn, victim.imsis[vn], victim.name, victim.address, _date(w.at(-900, 0, 0))),
        (l1, suspect.imsis[l1], lurer_alias, suspect.kyc_address[l1], _date(w.at(-40, 0, 0))),
        (s2, suspect.imsis[s2], _hindi(decoy_base), suspect.address, _date(w.at(-200, 0, 0))),
        (pa, mule_a.imsis[pa], mule_a.name, mule_a.address, _date(w.at(-300, 0, 0))),
        (pb, decoy_b.imsis[pb], decoy_b.name, decoy_b.address, _date(w.at(-1500, 0, 0))),
        (pc, mule_c.imsis[pc], mule_c.name, mule_c.address, _date(w.at(-400, 0, 0))),
        (pd2, decoy_d2.imsis[pd2], decoy_d2.name, decoy_d2.address, _date(w.at(-700, 0, 0))),
    ]
    accounts = [
        (va, victim.upis[va], victim.name, vn, victim.address, _date(w.at(-2000, 0, 0))),
        (a_account, mule_a.upis[a_account], mule_a.name, pa, mule_a.address, _date(w.at(-20, 0, 0))),
        (d2_account, decoy_d2.upis[d2_account], decoy_d2.name, pd2, decoy_d2.address, _date(w.at(-1000, 0, 0))),
    ]
    for person in l2_people:
        opened = w.at(-12, 0, 0) if person is mule_c else w.at(-rng.randint(400, 2200), 0, 0)
        accounts.append(
            (person.accounts[0], person.upis[person.accounts[0]], person.name, person.phones[0], person.address, _date(opened))
        )
    b.kyc_tables(subscribers, accounts)

    complaint_time = w.at(1, 10, rng.randint(5, 50))
    amounts_text = ", ".join(f"Rs {inr(amount)}" for amount in amounts)
    complaint = writer.text("complaint.txt", "complaint")
    complaint.add(f"Acknowledgement No: 3161{rng.randint(10**9, 10**10 - 1)}")
    complaint.add(f"Filed: {ist(complaint_time, '%Y-%m-%d %H:%M')}")
    complaint.add("Category: Online Financial Fraud / Investment Scam")
    complaint.add(f"Complainant: {victim.name}, {victim.address}")
    complaint.add(f"Mobile: {vn}")
    complaint.add("")
    complaint.add(
        f"Mere saath trading app ke naam par fraud hua hai. {t_contact.strftime('%d %b')} ko mujhe WhatsApp par {l1} se "
        "message aaya ki TradeX Prime app par invest karne se har mahine 25 se 30 percent return milega."
    )
    complaint.add("Unhone email bhi bheja jisme likha tha ki company SEBI registered hai.")
    complaint.add(
        f"Maine {payments[0][0].strftime('%d %b %Y')} ko UPI se {mule_a.upis[a_account]} par payment kiya: {amounts_text}."
    )
    complaint.add("Uske baad app mein profit dikha par withdrawal nahi hua, ab number band aa raha hai. Kripya madad karein.")
    complaint.add(f"Mera account: {va.split(':')[1]} (Indus Valley Bank)")

    writer.seed_identifiers = [{"type": "phone", "value": vn}, {"type": "account", "value": va}]
    writer.manifest_extra["complaint_time"] = ist(complaint_time)
    b.finalize()
    first_contact = writer.ref_tags["first_contact"][0]
    for event in b.truth["events"]:
        if event.get("tag") == "first_contact":
            event["ref"] = first_contact
            event.pop("tag")
    victim_ids = [
        f"phone:{vn}",
        f"imsi:{victim.imsis[vn]}",
        f"account:{va}",
        f"upi:{victim.upis[va]}",
        f"email:{victim.emails[0]}",
    ]
    suspect_ids = [
        f"phone:{l1}",
        f"phone:{s2}",
        f"imsi:{suspect.imsis[l1]}",
        f"imsi:{suspect.imsis[s2]}",
        f"imei:{h1}",
        f"imei:{h2}",
    ]
    if p.network:
        suspect_ids += [f"mac:{laptop_mac}", f"host:{hostname.lower()}", f"mac:{phone_mac}"]
    if p.cloud:
        suspect_ids.append(f"cloud:{cloud_account}")
    persons = {
        "victim": victim_ids,
        "suspect": suspect_ids,
        "mule_a": [f"account:{a_account}", f"upi:{mule_a.upis[a_account]}", f"phone:{pa}", f"imsi:{mule_a.imsis[pa]}"],
        "decoy_d2": [f"account:{d2_account}", f"upi:{decoy_d2.upis[d2_account]}", f"phone:{pd2}", f"imsi:{decoy_d2.imsis[pd2]}"],
    }
    for person in l2_people:
        persons[person.key] = [
            f"account:{person.accounts[0]}",
            f"upi:{person.upis[person.accounts[0]]}",
            f"phone:{person.phones[0]}",
            f"imsi:{person.imsis[person.phones[0]]}",
        ]
    truth = b.truth
    truth["class"] = "upi_investment_fraud"
    truth["persons"] = persons
    truth["roles"] = {
        "victim": "victim",
        "lurer": "suspect",
        "mule_l1": ["mule_a"],
        "mule_l2": [p.key for p in l2_people],
        "cashout": "suspect",
        "controller": "suspect" if p.network else None,
    }
    truth["variants"] = {"mule_l1": "knowing"}
    if p.utc_export:
        truth["clock"]["evidence/victim_phone/call_log.csv"] = {"offset_s": 19800, "kind": "timezone"}
        truth["clock"]["evidence/victim_phone/sms.csv"] = {"offset_s": 19800, "kind": "timezone"}
    truth["clock"][f"evidence/cctv/{atm_x.atm_id}_dvr_log.csv"] = {"offset_s": -p.dvr_offset_s, "kind": "drift"}
    cash_events = [wd["journal"] for wd in chain.withdrawals]
    truth["co_presence"] = [{"entity": f"phone:{s2}", "events": cash_events}]
    if p.cloud:
        truth["co_presence"].append({"entity": f"cloud:{cloud_account}", "events": cash_events})
    truth["impossible"] = [{"entity": f"phone:{pb}", "events": cash_events}] if decoy_b in l2_people else []
    truth["decoy_pairs"] = [[f"phone:{s2}", f"account:{d2_account}"], [f"phone:{s2}", f"phone:{pd2}"]]
    if decoy_b in l2_people:
        truth["decoy_pairs"] += [[f"phone:{s2}", f"account:{decoy_b.accounts[0]}"], [f"phone:{s2}", f"phone:{pb}"]]
    truth["money"] = {
        "victim_total": chain.victim_total,
        "tainted_accounts": [f"account:{a}" for a in chain.tainted_accounts],
        "cash_withdrawn": chain.cash_total,
        "cash_account": f"account:{c_account}",
        "cash_atm": atm_x.atm_id,
        "first_cash_time": chain.cash_times[0].timestamp(),
        "layering_time": min(e["time"] for e in truth["events"] if e["phase"] == "layering"),
    }
    truth["seed_identifiers"] = writer.seed_identifiers
    writer.truth = truth


def build_sextortion(world: World, writer: CaseWriter) -> None:
    w = world
    b = Builder(w, writer)
    rng = w.rng
    victim = w.person("victim", "GGN")
    victim.name = victim.name.split()[0] + " " + rng.choice(["Malhotra", "Bansal", "Khanna", "Arora"])
    extortionist = w.person("suspect", "JMT")
    vn = w.give_phone(victim)
    v_imei = w.give_handset(victim)
    bank_v = w.bank_by_code("CUBK")
    va = w.give_account(victim, bank_v, handle=victim.name.split()[0].lower() + str(rng.randint(10, 99)))
    x1 = w.give_phone(extortionist, kyc_name=w.name(), kyc_address=w.address("JMT"))
    x2 = w.give_phone(extortionist, kyc_name=w.name(), kyc_address=w.address("JMT"))
    hx = w.give_handset(extortionist)
    hx2 = w.give_handset(extortionist)
    mule = w.person("mule_a", "JMT")
    pm = w.give_phone(mule)
    ma = w.give_account(mule, w.bank_by_code("IVBK"), handle="pay.helpdesk")
    atm = w.atm_in("JMT")
    cash = w.person("mule_c", "JMT")
    pcash = w.give_phone(cash)
    ca = w.give_account(cash, w.bank_by_code(atm.bank))
    for person, account in [(victim, va), (mule, ma), (cash, ca)]:
        b.register_account(account, person, w.bank_by_code(account[:4]))
    b.open_statement(va, float(rng.randint(150, 300) * 1000))
    b.open_statement(ma, 0.0)
    b.open_statement(ca, 300.0)
    victim_background(b, victim, va)
    for msisdn in (x1, x2):
        b.cdr(msisdn)
    home_x = w.home_tower("JMT")
    victim_tuple = (vn, v_imei, victim.imsis[vn], w.home_tower("GGN"))
    x1_tuple = (x1, hx, extortionist.imsis[x1], home_x)
    b.victim_device(vn, utc_export=rng.random() < 0.5)
    victim_phone_background(b, victim_tuple)
    t0 = w.at(-1, 22, rng.randint(0, 40))
    label = x1[:3] + " " + x1[3:8] + " " + x1[8:]
    b.chat(x1, victim.name.split()[0], label)
    b.say(x1, t0, False, "Hi, kaise ho? Video call par baat karein?", tag="first_contact")
    b.say(x1, t0 + timedelta(minutes=3), False, "Missed video call")
    b.say(x1, t0 + timedelta(minutes=4), True, "Aap kaun?")
    b.call(x1_tuple, victim_tuple, t0 + timedelta(minutes=6), rng.randint(40, 90))
    t_threat = t0 + timedelta(minutes=rng.randint(20, 40))
    for index, line in enumerate(THREAT_LINES):
        b.say(x1, t_threat + timedelta(minutes=index * rng.randint(4, 12)), False, line)
    b.say(x1, t_threat + timedelta(minutes=9), True, "Please aisa mat karo, main paise bhej deta hoon.")
    b.say(x1, t_threat + timedelta(minutes=14), False, f"Is UPI par bhejo: {mule.upis[ma]}")
    b.truth["events"].append({"phase": "contact", "time": t0.timestamp(), "tag": "first_contact"})
    b.truth["events"].append({"phase": "threat", "time": t_threat.timestamp(), "ref": None})
    pay_start = w.at(0, 10, rng.randint(5, 40))
    payments = []
    moment = pay_start
    for _ in range(rng.randint(2, 3)):
        payments.append((moment, float(rng.randint(20, 50) * 1000)))
        moment += timedelta(minutes=rng.randint(30, 90))
    b.enable_cctv(atm, rng.uniform(-600, 600))
    chain = money_chain(b, va, ma, [ca], ca, atm, payments, {}, alert=True, commission=rng.uniform(1.0, 4.0))
    atm_background(b, atm, 0, rng.randint(8, 14))
    for day in range(-30, 1):
        if rng.random() < 0.7:
            b.cdr_row(
                x1,
                w.at(day, rng.randint(9, 22), rng.randint(0, 59)),
                w.phone(),
                "VOICE-MO",
                rng.randint(20, 300),
                hx,
                extortionist.imsis[x1],
                home_x,
            )
    b.call(
        x1_tuple, (pm, w.imei(), mule.imsis[pm], w.home_tower("JMT")), w.at(-15, 14, rng.randint(0, 50)), rng.randint(120, 400)
    )
    for day in (-5, -4):
        b.cdr_row(
            x2, w.at(day, 11, rng.randint(0, 59)), w.phone(), "VOICE-MO", rng.randint(30, 200), hx, extortionist.imsis[x2], home_x
        )
    near = w.tower_near(atm.lat, atm.lon)
    first = chain.cash_times[0]
    presence_series(
        b,
        x2,
        hx2,
        extortionist.imsis[x2],
        first - timedelta(minutes=5),
        chain.cash_times[-1] + timedelta(minutes=5),
        near,
        180,
        "INTERNET",
    )
    b.background_dump(atm, first - timedelta(minutes=30), first + timedelta(minutes=25), int(220 * w.scale))
    b.dump_row(atm, first - timedelta(minutes=3), near, x2, hx2, extortionist.imsis[x2])
    b.kyc_tables(
        [
            (vn, victim.imsis[vn], victim.name, victim.address, _date(w.at(-800, 0, 0))),
            (x1, extortionist.imsis[x1], extortionist.kyc_name[x1], extortionist.kyc_address[x1], _date(w.at(-60, 0, 0))),
            (x2, extortionist.imsis[x2], extortionist.kyc_name[x2], extortionist.kyc_address[x2], _date(w.at(-90, 0, 0))),
            (pm, mule.imsis[pm], mule.name, mule.address, _date(w.at(-500, 0, 0))),
            (pcash, cash.imsis[pcash], cash.name, cash.address, _date(w.at(-500, 0, 0))),
        ],
        [
            (va, victim.upis[va], victim.name, vn, victim.address, _date(w.at(-1500, 0, 0))),
            (ma, mule.upis[ma], mule.name, pm, mule.address, _date(w.at(-25, 0, 0))),
            (ca, cash.upis[ca], cash.name, pcash, cash.address, _date(w.at(-18, 0, 0))),
        ],
    )
    complaint_time = w.at(1, 11, rng.randint(0, 50))
    complaint = writer.text("complaint.txt", "complaint")
    complaint.add(f"Acknowledgement No: 3162{rng.randint(10**9, 10**10 - 1)}")
    complaint.add(f"Filed: {ist(complaint_time, '%Y-%m-%d %H:%M')}")
    complaint.add("Category: Online and Social Media Related Crime / Sextortion")
    complaint.add(f"Complainant: {victim.name}, {victim.address}")
    complaint.add(f"Mobile: {vn}")
    complaint.add("")
    complaint.add(f"Raat ko {x1} se WhatsApp video call aaya, uske baad mujhe dhamki di gayi ki mera video viral kar denge.")
    complaint.add(
        f"Darr ke kaaran maine {mule.upis[ma]} par paise bheje: "
        + ", ".join(f"Rs {inr(amount)}" for _, amount in payments)
        + ". Ab aur paise maang rahe hain."
    )
    writer.seed_identifiers = [{"type": "phone", "value": vn}, {"type": "account", "value": va}]
    writer.manifest_extra["complaint_time"] = ist(complaint_time)
    b.finalize()
    first_contact = writer.ref_tags["first_contact"][0]
    events = []
    for event in b.truth["events"]:
        if event.get("tag") == "first_contact":
            event["ref"] = first_contact
            event.pop("tag")
        if event.get("ref") is not None:
            events.append(event)
    truth = b.truth
    truth["events"] = events
    truth["class"] = "sextortion"
    truth["persons"] = {
        "victim": [f"phone:{vn}", f"account:{va}", f"upi:{victim.upis[va]}", f"imsi:{victim.imsis[vn]}"],
        "suspect": [
            f"phone:{x1}",
            f"phone:{x2}",
            f"imei:{hx}",
            f"imei:{hx2}",
            f"imsi:{extortionist.imsis[x1]}",
            f"imsi:{extortionist.imsis[x2]}",
        ],
        "mule_a": [f"account:{ma}", f"upi:{mule.upis[ma]}", f"phone:{pm}", f"imsi:{mule.imsis[pm]}"],
        "mule_c": [f"account:{ca}", f"upi:{cash.upis[ca]}", f"phone:{pcash}", f"imsi:{cash.imsis[pcash]}"],
    }
    truth["roles"] = {
        "victim": "victim",
        "extortionist": "suspect",
        "mule_l1": ["mule_a"],
        "mule_l2": ["mule_c"],
        "cashout": "suspect",
    }
    cash_events = [wd["journal"] for wd in chain.withdrawals]
    truth["co_presence"] = [{"entity": f"phone:{x2}", "events": cash_events}]
    truth["money"] = {
        "victim_total": chain.victim_total,
        "tainted_accounts": [f"account:{ma}", f"account:{ca}"],
        "cash_withdrawn": chain.cash_total,
        "cash_account": f"account:{ca}",
        "cash_atm": atm.atm_id,
        "first_cash_time": chain.cash_times[0].timestamp(),
        "layering_time": min(e["time"] for e in events if e["phase"] == "layering"),
    }
    if b.victim_export_utc:
        truth["clock"]["evidence/victim_phone/call_log.csv"] = {"offset_s": 19800, "kind": "timezone"}
    truth["clock"][f"evidence/cctv/{atm.atm_id}_dvr_log.csv"] = {"offset_s": -b.cctv[atm.atm_id]["offset"], "kind": "drift"}
    truth["seed_identifiers"] = writer.seed_identifiers
    writer.truth = truth


def build_sim_swap(world: World, writer: CaseWriter) -> None:
    w = world
    b = Builder(w, writer)
    rng = w.rng
    victim = w.person("victim", "CPL")
    swapper = w.person("suspect", "JMT")
    vn = w.give_phone(victim)
    v_imei = w.give_handset(victim)
    old_imsi = victim.imsis[vn]
    new_imsi = w.imsi()
    hs = w.give_handset(swapper)
    sw = w.give_phone(swapper)
    bank_v = w.bank_by_code("IVBK")
    va = w.give_account(victim, bank_v, handle=victim.name.split()[0].lower() + str(rng.randint(100, 999)))
    mule = w.person("mule_a", "JMT")
    pm = w.give_phone(mule)
    ma = w.give_account(mule, w.bank_by_code("NCBK"))
    atm = w.atm_in("JMT")
    cash = w.person("mule_c", "JMT")
    pcash = w.give_phone(cash)
    ca = w.give_account(cash, w.bank_by_code(atm.bank))
    for person, account in [(victim, va), (mule, ma), (cash, ca)]:
        b.register_account(account, person, w.bank_by_code(account[:4]))
    b.open_statement(va, float(rng.randint(250, 600) * 1000))
    b.open_statement(ma, 1000.0)
    b.open_statement(ca, 200.0)
    victim_background(b, victim, va)
    b.cdr(vn)
    b.cdr(sw)
    home_v = w.home_tower("CPL")
    home_s = w.home_tower("JMT")
    victim_tuple = (vn, v_imei, old_imsi, home_v)
    b.victim_device(vn, utc_export=False)
    family = [(w.phone(), w.imei(), w.imsi(), w.home_tower("CPL")) for _ in range(5)]
    for day in range(-45, 0):
        for _ in range(rng.randint(0, 3)):
            b.call(
                victim_tuple,
                rng.choice(family),
                w.at(day, rng.randint(8, 21), rng.randint(0, 59), rng.randint(0, 59)),
                rng.randint(30, 600),
            )
    t_swap = w.at(0, 11, rng.randint(0, 30))
    b.call(victim_tuple, rng.choice(family), t_swap - timedelta(minutes=rng.randint(20, 60)), rng.randint(60, 300))
    swap_ref = b.cdr_row(vn, t_swap, "SIM-ACTIVATION", "NETWORK", 0, hs, new_imsi, home_s)
    b.truth["events"].append({"phase": "sim_change", "time": t_swap.timestamp(), "ref": swap_ref})
    otp_times = [t_swap + timedelta(minutes=rng.randint(8, 14)), t_swap + timedelta(minutes=rng.randint(16, 22))]
    for moment in otp_times:
        ref = b.cdr_row(vn, moment, "IV-IVBANK", "SMS-MT", 0, hs, new_imsi, home_s)
        b.truth["events"].append({"phase": "otp", "time": moment.timestamp(), "ref": ref})
    for day in range(-20, 0):
        if rng.random() < 0.6:
            b.cdr_row(
                sw,
                w.at(day, rng.randint(9, 21), rng.randint(0, 59)),
                w.phone(),
                "VOICE-MO",
                rng.randint(20, 300),
                hs,
                swapper.imsis[sw],
                home_s,
            )
    payments = []
    moment = otp_times[-1] + timedelta(minutes=rng.randint(3, 8))
    for _ in range(rng.randint(2, 3)):
        payments.append((moment, float(rng.randint(40, 95) * 1000)))
        moment += timedelta(minutes=rng.randint(3, 9))
    b.enable_cctv(atm, rng.uniform(-500, 500))
    chain = money_chain(b, va, ma, [ca], ca, atm, payments, {}, alert=False, commission=rng.uniform(1.0, 3.0))
    for event in b.truth["events"]:
        if event["phase"] == "payment":
            event["phase"] = "unauthorized_debit"
    atm_background(b, atm, 0, rng.randint(8, 14))
    near = w.tower_near(atm.lat, atm.lon)
    first = chain.cash_times[0]
    presence_series(
        b,
        sw,
        hs,
        swapper.imsis[sw],
        first - timedelta(minutes=5),
        chain.cash_times[-1] + timedelta(minutes=5),
        near,
        200,
        "INTERNET",
    )
    b.background_dump(atm, first - timedelta(minutes=30), first + timedelta(minutes=25), int(220 * w.scale))
    b.dump_row(atm, first - timedelta(minutes=2), near, sw, hs, swapper.imsis[sw])
    b.kyc_tables(
        [
            (vn, old_imsi, victim.name, victim.address, _date(w.at(-1200, 0, 0))),
            (sw, swapper.imsis[sw], w.name(), w.address("JMT"), _date(w.at(-120, 0, 0))),
            (pm, mule.imsis[pm], mule.name, mule.address, _date(w.at(-600, 0, 0))),
            (pcash, cash.imsis[pcash], cash.name, cash.address, _date(w.at(-600, 0, 0))),
        ],
        [
            (va, victim.upis[va], victim.name, vn, victim.address, _date(w.at(-2500, 0, 0))),
            (ma, mule.upis[ma], mule.name, pm, mule.address, _date(w.at(-30, 0, 0))),
            (ca, cash.upis[ca], cash.name, pcash, cash.address, _date(w.at(-22, 0, 0))),
        ],
    )
    complaint_time = w.at(0, 17, rng.randint(0, 50))
    complaint = writer.text("complaint.txt", "complaint")
    complaint.add(f"Acknowledgement No: 3163{rng.randint(10**9, 10**10 - 1)}")
    complaint.add(f"Filed: {ist(complaint_time, '%Y-%m-%d %H:%M')}")
    complaint.add("Category: Online Financial Fraud / SIM Swap")
    complaint.add(f"Complainant: {victim.name}, {victim.address}")
    complaint.add(f"Mobile: {vn}")
    complaint.add("")
    complaint.add(
        f"Aaj subah lagbhag {t_swap.strftime('%H:%M')} baje mera phone {vn} achanak band ho gaya, network nahi aa raha tha."
    )
    complaint.add(
        "Shaam ko bank jaakar pata chala ki mere account se bina meri jaankari ke IMPS se paise nikal liye gaye: "
        + ", ".join(f"Rs {inr(amount)}" for _, amount in payments)
        + "."
    )
    complaint.add("Maine koi OTP kisi ko nahi diya.")
    writer.seed_identifiers = [{"type": "phone", "value": vn}, {"type": "account", "value": va}]
    writer.manifest_extra["complaint_time"] = ist(complaint_time)
    b.finalize()
    truth = b.truth
    truth["class"] = "sim_swap_takeover"
    truth["persons"] = {
        "victim": [f"phone:{vn}", f"imsi:{old_imsi}", f"imei:{v_imei}", f"account:{va}", f"upi:{victim.upis[va]}"],
        "suspect": [f"phone:{sw}", f"imsi:{swapper.imsis[sw]}", f"imei:{hs}", f"imsi:{new_imsi}"],
        "mule_a": [f"account:{ma}", f"upi:{mule.upis[ma]}", f"phone:{pm}", f"imsi:{mule.imsis[pm]}"],
        "mule_c": [f"account:{ca}", f"upi:{cash.upis[ca]}", f"phone:{pcash}", f"imsi:{cash.imsis[pcash]}"],
    }
    truth["roles"] = {
        "victim": "victim",
        "swapper": "suspect",
        "mule_l1": ["mule_a"],
        "mule_l2": ["mule_c"],
        "cashout": "suspect",
    }
    cash_events = [wd["journal"] for wd in chain.withdrawals]
    truth["co_presence"] = [{"entity": f"phone:{sw}", "events": cash_events}]
    truth["money"] = {
        "victim_total": chain.victim_total,
        "tainted_accounts": [f"account:{ma}", f"account:{ca}"],
        "cash_withdrawn": chain.cash_total,
        "cash_account": f"account:{ca}",
        "cash_atm": atm.atm_id,
        "first_cash_time": chain.cash_times[0].timestamp(),
        "layering_time": min(e["time"] for e in truth["events"] if e["phase"] == "layering"),
    }
    truth["clock"][f"evidence/cctv/{atm.atm_id}_dvr_log.csv"] = {"offset_s": -b.cctv[atm.atm_id]["offset"], "kind": "drift"}
    truth["seed_identifiers"] = writer.seed_identifiers
    writer.truth = truth


def build_benign(world: World, writer: CaseWriter) -> None:
    w = world
    b = Builder(w, writer)
    rng = w.rng
    victim = w.person("victim", "LXN")
    merchant = w.person("merchant", "LXN", rng.choice(["Shree Furniture House", "Gupta Home Decor", "Royal Interiors"]))
    vn = w.give_phone(victim)
    v_imei = w.give_handset(victim)
    mn = w.give_phone(merchant)
    va = w.give_account(victim, w.bank_by_code("CUBK"))
    mac = w.give_account(merchant, w.bank_by_code("NCBK"), handle=merchant.name.split()[0].lower() + "store")
    for person, account in [(victim, va), (merchant, mac)]:
        b.register_account(account, person, w.bank_by_code(account[:4]))
    b.open_statement(va, float(rng.randint(120, 300) * 1000))
    b.open_statement(mac, float(rng.randint(150, 400) * 1000))
    victim_background(b, victim, va)
    for day in (-70, -40):
        b.transfer(
            va,
            mac,
            float(rng.randint(5, 18) * 1000),
            w.at(day, rng.randint(11, 18), rng.randint(0, 59)),
            "UPI",
            "Furniture order",
        )
    for _ in range(30):
        day = -rng.randint(0, 60)
        b.external_credit(
            mac,
            float(rng.randint(3, 60) * 1000),
            w.at(day, rng.randint(10, 20), rng.randint(0, 59)),
            "Customer",
            "UPI",
            channel="UPI",
        )
    for _ in range(12):
        day = -rng.randint(0, 60)
        b.external_debit(
            mac,
            float(rng.randint(10, 80) * 1000),
            w.at(day, rng.randint(10, 18), rng.randint(0, 59)),
            "Timber Suppliers",
            "NEFT",
            channel="NEFT",
        )
    t_pay = w.at(0, 12, rng.randint(0, 50))
    debit, _, _ = b.transfer(va, mac, 45000.0, t_pay, "UPI", "Sofa set order")
    b.truth["events"].append({"phase": "payment", "time": t_pay.timestamp(), "ref": debit})
    b.external_debit(mac, 30000.0, w.at(1, 15, 10), "Timber Suppliers", "NEFT", channel="NEFT")
    b.victim_device(vn, utc_export=False)
    b.chat(mn, victim.name.split()[0], merchant.name)
    for index, line in enumerate(BENIGN_LINES):
        b.say(mn, t_pay + timedelta(days=index * 3, hours=2), False, line)
    b.say(mn, t_pay + timedelta(days=4), True, "Delivery kab tak hogi? Bahut din ho gaye.")
    b.call(
        (vn, v_imei, victim.imsis[vn], w.home_tower("LXN")),
        (mn, w.imei(), merchant.imsis[mn], w.home_tower("LXN")),
        t_pay + timedelta(days=6),
        rng.randint(60, 240),
    )
    b.kyc_tables(
        [],
        [
            (va, victim.upis[va], victim.name, vn, victim.address, _date(w.at(-1800, 0, 0))),
            (mac, merchant.upis[mac], merchant.name, mn, merchant.address, _date(w.at(-2400, 0, 0))),
        ],
    )
    complaint_time = w.at(11, 10, rng.randint(0, 50))
    complaint = writer.text("complaint.txt", "complaint")
    complaint.add(f"Acknowledgement No: 3164{rng.randint(10**9, 10**10 - 1)}")
    complaint.add(f"Filed: {ist(complaint_time, '%Y-%m-%d %H:%M')}")
    complaint.add("Category: Online Financial Fraud / Other")
    complaint.add(f"Complainant: {victim.name}, {victim.address}")
    complaint.add(f"Mobile: {vn}")
    complaint.add("")
    complaint.add(f"Maine {merchant.name} ko sofa set ke liye Rs 45,000 UPI se {merchant.upis[mac]} par bheje the.")
    complaint.add("10 din ho gaye, delivery nahi hui. Dukaan wale har baar kal bol dete hain. Mujhe darr hai ki yeh fraud hai.")
    writer.seed_identifiers = [{"type": "phone", "value": vn}, {"type": "account", "value": va}]
    writer.manifest_extra["complaint_time"] = ist(complaint_time)
    b.finalize()
    truth = b.truth
    truth["class"] = "no_offence"
    truth["persons"] = {
        "victim": [f"phone:{vn}", f"account:{va}", f"upi:{victim.upis[va]}"],
        "merchant": [f"phone:{mn}", f"account:{mac}", f"upi:{merchant.upis[mac]}"],
    }
    truth["roles"] = {"victim": "victim"}
    truth["money"] = {"victim_total": 0.0, "tainted_accounts": [], "cash_withdrawn": 0.0}
    truth["seed_identifiers"] = writer.seed_identifiers
    writer.truth = truth


def build_unknown(world: World, writer: CaseWriter) -> None:
    w = world
    b = Builder(w, writer)
    rng = w.rng
    company = rng.choice(["Kaveri Analytics Pvt Ltd", "Saraswati Ledger Services", "Tapti Data Labs"])
    contact_email = f"it.admin@{company.split()[0].lower()}.test"
    server_ip, server_mac = "10.0.0.15", "00:1b:21:" + ":".join(f"{rng.randint(0, 255):02x}" for _ in range(3))
    exfil_ip = "192.0.2.80"
    first = None
    for day in (-2, -1, 0):
        moment = w.at(day, 1, rng.randint(20, 40))
        end = w.at(day, 3, 10)
        while moment < end:
            ref = b.net(
                moment,
                server_ip,
                server_mac,
                exfil_ip,
                443,
                "sync.cloudstore-files.test",
                rng.randint(4_000_000, 22_000_000),
                rng.randint(2000, 9000),
            )
            first = first or (moment, ref)
            moment += timedelta(seconds=rng.randint(40, 90))
        moment = w.at(day, 0, 0)
        while moment < w.at(day, 23, 59):
            b.net(
                moment,
                server_ip,
                server_mac,
                exfil_ip,
                8443,
                "sync.cloudstore-files.test",
                rng.randint(300, 600),
                rng.randint(500, 900),
            )
            moment += timedelta(seconds=300 + rng.uniform(-6, 6))
        for _ in range(80):
            client = f"10.0.0.{rng.randint(30, 90)}"
            b.net(
                w.at(day, rng.randint(9, 19), rng.randint(0, 59), rng.randint(0, 59)),
                client,
                "8c:16:45:" + ":".join(f"{rng.randint(0, 255):02x}" for _ in range(3)),
                f"192.0.2.{rng.randint(100, 250)}",
                443,
                rng.choice(["mail.office.test", "docs.office.test", "erp.vendor.test"]),
                rng.randint(900, 90000),
                rng.randint(5000, 900000),
            )
    incident = {
        "tool": "UniAethel",
        "version": "1.0",
        "capture": {"file": "office_span.pcap", "start_utc": w.at(-2, 0, 0).isoformat()},
        "incidents": [
            {
                "id": "INC-001",
                "host": server_ip,
                "label": "EXFIL",
                "trajectory": "Persistent",
                "window": {"start": w.at(-2, 1, 20).isoformat(), "end": w.at(0, 3, 10).isoformat()},
                "counterparty": {"top_destination": exfil_ip, "distinct_destinations": 1},
                "scores": {"C2": 0.31, "RECON": 0.05, "DDOS": 0.0, "EXFIL": 0.77},
                "evidence_vector": {"A_M": 0.88, "A_IF": 0.74, "A_TCN": 0.62, "A_G": 0.81},
                "reasons": ["outbound volume far above host baseline", "transfers concentrated in off-hours"],
            },
        ],
    }
    b.cw.text("network/uniaethel_incidents.json", "uniaethel", raw_json=True).add(json_text(incident))
    b.email(
        "ransom_note.eml",
        ("Data Recovery Team", "recovery-desk@securemail.test"),
        ("IT Admin", contact_email),
        w.at(0, 9, rng.randint(0, 40)),
        "Your files are with us",
        "We have copied your client database and accounts files. Pay 1.5 BTC to the wallet below within 72 hours or we will "
        "leak everything to your clients and publish it online.\nWallet: bc1qexampleexampleexampleexample0000\n"
        "Do not contact police.",
        "192.0.2.201",
    )
    complaint_time = w.at(0, 15, rng.randint(0, 50))
    complaint = writer.text("complaint.txt", "complaint")
    complaint.add(f"Acknowledgement No: 3165{rng.randint(10**9, 10**10 - 1)}")
    complaint.add(f"Filed: {ist(complaint_time, '%Y-%m-%d %H:%M')}")
    complaint.add("Category: Cyber Attack / Data Breach")
    complaint.add(f"Complainant: {company}, IT administrator ({contact_email})")
    complaint.add("")
    complaint.add(
        "Hamare file server se client data chori hua hai aur ek email aaya hai jisme Bitcoin mein paise maange gaye hain."
    )
    complaint.add("Router logs aur network analysis report saath mein di gayi hai.")
    writer.seed_identifiers = [{"type": "email", "value": contact_email}, {"type": "mac", "value": server_mac}]
    writer.seed_kind = "complaint"
    writer.manifest_extra["complaint_time"] = ist(complaint_time)
    b.finalize()
    truth = b.truth
    truth["class"] = "unknown"
    truth["persons"] = {"victim": [f"email:{contact_email}", f"mac:{server_mac}"]}
    truth["roles"] = {"victim": "victim"}
    truth["money"] = {"victim_total": 0.0, "tainted_accounts": [], "cash_withdrawn": 0.0}
    truth["events"] = [{"phase": "control", "time": first[0].timestamp(), "ref": first[1]}]
    truth["seed_identifiers"] = writer.seed_identifiers
    writer.truth = truth
