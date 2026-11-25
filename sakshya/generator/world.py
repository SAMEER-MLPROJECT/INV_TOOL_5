from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sakshya.core.geo import haversine_m, offset_point
from sakshya.core.identifiers import luhn_valid
from sakshya.core.timeutil import IST


@dataclass(frozen=True)
class Hub:
    code: str
    name: str
    lat: float
    lon: float
    address: str


@dataclass(frozen=True)
class Tower:
    cell_id: str
    hub: str
    lat: float
    lon: float
    radius_m: int
    address: str


@dataclass(frozen=True)
class Atm:
    atm_id: str
    bank: str
    hub: str
    lat: float
    lon: float
    address: str


@dataclass(frozen=True)
class Bank:
    code: str
    name: str
    handle: str


HUBS = [
    Hub("DWK", "Dwarka", 28.5921, 77.0460, "Sector 10, Dwarka, New Delhi"),
    Hub("NOI", "Noida Sector 18", 28.5708, 77.3261, "Sector 18, Noida, Uttar Pradesh"),
    Hub("LXN", "Laxmi Nagar", 28.6304, 77.2775, "Laxmi Nagar, Delhi"),
    Hub("CPL", "Connaught Place", 28.6315, 77.2167, "Connaught Place, New Delhi"),
    Hub("GGN", "Gurugram", 28.4687, 77.0631, "Sector 29, Gurugram, Haryana"),
    Hub("PAT", "Patna", 25.6110, 85.1440, "Boring Road, Patna, Bihar"),
    Hub("JMT", "Jamtara", 23.9625, 86.8020, "Main Road, Jamtara, Jharkhand"),
    Hub("LKO", "Lucknow", 26.8467, 80.9462, "Hazratganj, Lucknow, Uttar Pradesh"),
]

BANKS = [
    Bank("IVBK", "Indus Valley Bank", "ivb"),
    Bank("NCBK", "Narmada Co-operative Bank", "ncb"),
    Bank("GGBK", "Ganga Gramin Bank", "ggb"),
    Bank("CUBK", "Coastal Union Bank", "cub"),
]

FIRST_NAMES = [
    "Aarav",
    "Vivaan",
    "Aditya",
    "Vihaan",
    "Arjun",
    "Sai",
    "Reyansh",
    "Ayaan",
    "Krishna",
    "Ishaan",
    "Ananya",
    "Diya",
    "Aadhya",
    "Saanvi",
    "Pari",
    "Anika",
    "Navya",
    "Myra",
    "Sara",
    "Ira",
    "Rahul",
    "Sanjay",
    "Deepak",
    "Manoj",
    "Suresh",
    "Kavita",
    "Sunita",
    "Neha",
    "Priya",
    "Pooja",
    "Vikas",
    "Rakesh",
    "Mukesh",
    "Ravi",
    "Anil",
    "Geeta",
    "Rekha",
    "Seema",
    "Nitin",
    "Harish",
]
SURNAMES = [
    "Sharma",
    "Verma",
    "Gupta",
    "Singh",
    "Kumar",
    "Yadav",
    "Mishra",
    "Jain",
    "Agarwal",
    "Chauhan",
    "Reddy",
    "Nair",
    "Iyer",
    "Das",
    "Mehta",
    "Patel",
    "Joshi",
    "Pandey",
    "Tiwari",
    "Saxena",
]
DEVANAGARI = {
    "Rohit Kumar": "रोहित कुमार",
    "Sunil Verma": "सुनील वर्मा",
    "Amit Yadav": "अमित यादव",
    "Pooja Singh": "पूजा सिंह",
    "Ravi Mishra": "रवि मिश्रा",
}


@dataclass
class Person:
    key: str
    name: str
    hub: str
    address: str
    phones: list[str] = field(default_factory=list)
    imeis: list[str] = field(default_factory=list)
    imsis: dict[str, str] = field(default_factory=dict)
    accounts: list[str] = field(default_factory=list)
    upis: dict[str, str] = field(default_factory=dict)
    emails: list[str] = field(default_factory=list)
    kyc_name: dict[str, str] = field(default_factory=dict)
    kyc_address: dict[str, str] = field(default_factory=dict)


class World:
    def __init__(self, seed: int, scale: float = 1.0, base_day: datetime | None = None) -> None:
        self.rng = random.Random(seed)
        self.seed = seed
        self.scale = scale
        self.used: set[str] = set()
        self.towers: list[Tower] = []
        self.atms: list[Atm] = []
        self.hubs = {hub.code: hub for hub in HUBS}
        if base_day is None:
            start = datetime(2026, 9, 7, tzinfo=IST)
            base_day = start + timedelta(days=self.rng.randint(0, 60))
        self.base_day = base_day.replace(hour=0, minute=0, second=0, microsecond=0)
        self._build_towers()
        self._build_atms()

    def _unique(self, factory) -> str:
        for _ in range(10_000):
            value = factory()
            if value not in self.used:
                self.used.add(value)
                return value
        raise RuntimeError("identifier space exhausted")

    def _build_towers(self) -> None:
        for hub in HUBS:
            count = 8 if hub.code in {"NOI", "DWK", "LXN"} else 5
            for index in range(count):
                if index == 0:
                    lat, lon = offset_point(hub.lat, hub.lon, self.rng.uniform(-150, 150), self.rng.uniform(-150, 150))
                else:
                    lat, lon = offset_point(hub.lat, hub.lon, self.rng.uniform(-2600, 2600), self.rng.uniform(-2600, 2600))
                radius = self.rng.choice([650, 800, 900, 1000, 1200, 1500])
                cell = f"{hub.code}-{4100 + index * 7 + self.rng.randint(0, 6):05d}"
                self.towers.append(
                    Tower(cell, hub.code, round(lat, 6), round(lon, 6), radius, f"Site {index + 1}, {hub.address}")
                )

    def _build_atms(self) -> None:
        for hub in HUBS:
            for index, bank in enumerate(self.rng.sample(BANKS, 2)):
                lat, lon = offset_point(hub.lat, hub.lon, self.rng.uniform(-500, 500), self.rng.uniform(-500, 500))
                atm_id = f"ATM-{bank.code}-{hub.code}-{index + 1:02d}"
                self.atms.append(
                    Atm(atm_id, bank.code, hub.code, round(lat, 6), round(lon, 6), f"{bank.name} ATM, {hub.address}")
                )

    def at(self, day_offset: float, hour: int, minute: int, second: int = 0) -> datetime:
        return self.base_day + timedelta(days=day_offset, hours=hour, minutes=minute, seconds=second)

    def phone(self) -> str:
        return self._unique(lambda: "+91" + self.rng.choice("6789") + "".join(self.rng.choice("0123456789") for _ in range(9)))

    def imei(self) -> str:
        def make() -> str:
            body = "35" + "".join(self.rng.choice("0123456789") for _ in range(12))
            for check in range(10):
                if luhn_valid(body + str(check)):
                    return body + str(check)
            return body + "0"

        return self._unique(make)

    def imsi(self) -> str:
        return self._unique(
            lambda: "4041" + self.rng.choice("0123456789") + "".join(self.rng.choice("0123456789") for _ in range(10))
        )

    def account(self, bank: Bank) -> str:
        return self._unique(
            lambda: (
                f"{bank.code}0{self.rng.randint(100000, 999999)}:{self.rng.randint(10, 99)}{self.rng.randint(10**10, 10**11 - 1)}"
            )
        )

    def upi_ref(self) -> str:
        return self._unique(lambda: str(self.rng.randint(10**11, 10**12 - 1)))

    def name(self) -> str:
        return f"{self.rng.choice(FIRST_NAMES)} {self.rng.choice(SURNAMES)}"

    def bank(self, exclude: str | None = None) -> Bank:
        choices = [b for b in BANKS if b.code != exclude]
        return self.rng.choice(choices)

    def bank_by_code(self, code: str) -> Bank:
        return next(b for b in BANKS if b.code == code)

    def towers_in(self, hub: str) -> list[Tower]:
        return [t for t in self.towers if t.hub == hub]

    def home_tower(self, hub: str) -> Tower:
        return self.rng.choice(self.towers_in(hub))

    def tower_near(self, lat: float, lon: float) -> Tower:
        return min(self.towers, key=lambda t: haversine_m(lat, lon, t.lat, t.lon))

    def towers_covering(self, lat: float, lon: float, extra_m: float = 1500) -> list[Tower]:
        return [t for t in self.towers if haversine_m(lat, lon, t.lat, t.lon) <= t.radius_m + extra_m]

    def atm_in(self, hub: str) -> Atm:
        return next(a for a in self.atms if a.hub == hub)

    def address(self, hub: str) -> str:
        house = self.rng.randint(11, 480)
        block = self.rng.choice("ABCDEFGH")
        return f"H.No. {house}, Block {block}, {self.hubs[hub].address}"

    def person(self, key: str, hub: str, name: str | None = None) -> Person:
        return Person(key=key, name=name or self.name(), hub=hub, address=self.address(hub))

    def give_phone(self, person: Person, kyc_name: str | None = None, kyc_address: str | None = None) -> str:
        number = self.phone()
        person.phones.append(number)
        person.imsis[number] = self.imsi()
        person.kyc_name[number] = kyc_name or person.name
        person.kyc_address[number] = kyc_address or person.address
        return number

    def give_handset(self, person: Person) -> str:
        imei = self.imei()
        person.imeis.append(imei)
        return imei

    def give_account(self, person: Person, bank: Bank | None = None, handle: str | None = None) -> str:
        bank = bank or self.bank()
        account = self.account(bank)
        person.accounts.append(account)
        local = handle or f"{person.name.split()[0].lower()}{self.rng.randint(10, 9999)}"
        person.upis[account] = f"{local}@{bank.handle}"
        return account
