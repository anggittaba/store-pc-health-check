"""Synthetic daily health pulls for a fleet of fictional stores.

Everything here is invented: store names, codes, PCs and readings. The generator also
records which faults it injected ("ground truth"), so the rule engine can be scored
against it. That score only says the rules match *this* simulator, not a real fleet.

The simulation is deterministic: the same seed and start date always give the same
history, so `generate-today` re-simulates from the start date and only inserts the
days that are missing. Earlier days never change.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

SEED = 35  # picked from seeds 1-40 because its last day shows a bit of everything; see README
N_STORES = 60
BURN_IN_DAYS = 25  # simulated before the first stored day, so faults are already in progress on day 1

STREETS = [
    "Juniper", "Harbour", "Millbrook", "Cedar", "Larkspur", "Foundry", "Orchard", "Kestrel", "Quarry", "Bramble",
    "Linden", "Copper", "Saltmarsh", "Heron", "Wicker", "Marigold", "Granary", "Ashgrove", "Thistle", "Lantern",
    "Pebble", "Rowan", "Tanner", "Bluebell", "Clover", "Ferry", "Hawthorn", "Ironleaf", "Kiln", "Meadow",
    "Nettle", "Oakridge", "Pine", "Quayside", "Reed", "Sorrel", "Timber", "Upland", "Willow", "Yarrow",
    "Alder", "Beacon", "Chestnut", "Dovecote", "Elm", "Fieldgate", "Glen", "Hazel", "Ivy", "Jasmine",
    "Wrenfield", "Laurel", "Maple", "Northgate", "Osprey", "Poplar", "Rookery", "Spindle", "Tern", "Violet",
]
SUFFIX = ["Road", "Lane", "Street", "Square", "Parade", "Way"]
AREAS = ["Area A", "Area B", "Area C", "Area D", "Area E", "Area F"]
CPUS = ["Core i3-8100", "Core i3-10100", "Core i5-10400", "Pentium G6400", "Core i3-12100"]
OS_BUILDS = ["Windows 10 Pro 22H2 (19045)", "Windows 11 Pro 23H2 (22631)", "Windows 11 Pro 24H2 (26100)"]

ISSUE_TYPES = ["edc_offline", "lan_degraded", "missing_pull", "overheating", "disk_smart", "disk_space",
               "ups_problem", "ram_below_spec", "no_reboot", "windows_activation"]

# Daily chance that a new fault episode starts on one PC (or store, for missing_pull).
START_P = {
    "overheating": 0.0028, "disk_space": 0.0024, "ram_below_spec": 0.0010, "no_reboot": 0.0025,
    "windows_activation": 0.0010, "edc_offline": 0.0040, "ups_problem": 0.0022, "lan_degraded": 0.0028,
    "disk_smart": 0.0008, "missing_pull": 0.0070, "lan_store": 0.0008,
}
# Noise that looks like a fault for one day but is not one (counts against precision if flagged).
NOISE_P = {"temp_spike": 0.02, "lan_blip": 0.010, "edc_blip": 0.008, "ups_blip": 0.004}
RECUR_P = 0.35  # flaky hardware: chance a fixed fault comes back a few days later
NO_REBOOT_ONSET = 7  # the generator's own definition: a PC up 7+ days has missed its weekly restart


@dataclass
class Episode:
    kind: str
    day: int = 0
    length: int = 3
    variant: str = ""
    params: dict = field(default_factory=dict)


@dataclass
class PC:
    pc_id: str
    store_code: str
    role: str
    has_edc: bool
    cpu: str
    os_build: str
    ram_spec: int
    disk_total: int
    disk_used: float
    disk_growth: float
    base_temp: float
    reboot_every: int
    uptime: int = 0
    episodes: dict = field(default_factory=dict)
    pending: dict = field(default_factory=dict)  # kind -> days until a recurrence starts
    ups_battery: float = 98.0


@dataclass
class Store:
    code: str
    name: str
    area: str
    pcs: list
    missing: Episode | None = None
    lan: Episode | None = None


def build_fleet(rng: random.Random) -> list[Store]:
    names = STREETS[:]
    rng.shuffle(names)
    stores = []
    for i in range(N_STORES):
        code = f"ST-{101 + i * 7:03d}"
        n_pcs = rng.choices([1, 2, 3], weights=[2, 5, 3])[0]
        roles = ["Till 1", "Till 2", "Back office"][:n_pcs] if n_pcs > 1 else ["Till 1"]
        if n_pcs == 2 and rng.random() < 0.5:
            roles = ["Till 1", "Back office"]
        pcs = []
        for j, role in enumerate(roles, 1):
            office = role == "Back office"
            pcs.append(PC(
                pc_id=f"{code}-PC{j}", store_code=code, role=role, has_edc=not office,
                cpu=rng.choice(CPUS), os_build=rng.choices(OS_BUILDS, weights=[5, 4, 2])[0],
                ram_spec=16 if office and rng.random() < 0.5 else 8,
                disk_total=rng.choice([256, 256, 512, 1000] if office else [128, 256, 256]),
                disk_used=rng.uniform(38, 72), disk_growth=rng.uniform(0.02, 0.2),
                base_temp=rng.uniform(42, 61), reboot_every=rng.choice([1, 1, 1, 2, 3]),
                ups_battery=rng.uniform(88, 100),
            ))
        stores.append(Store(code=code, name=f"{names[i]} {rng.choice(SUFFIX)}", area=AREAS[i % len(AREAS)], pcs=pcs))
    return stores


def _new_episode(kind: str, rng: random.Random) -> Episode:
    if kind == "overheating":
        return Episode(kind, length=rng.randint(3, 9), params={"peak": rng.uniform(87, 99), "start": rng.uniform(79, 86)})
    if kind == "disk_space":
        return Episode(kind, length=rng.randint(4, 10), params={"start": rng.uniform(85, 89), "rate": rng.uniform(1.8, 3.2)})
    if kind == "ram_below_spec":
        return Episode(kind, length=rng.randint(5, 14))
    if kind == "no_reboot":
        return Episode(kind, length=rng.randint(10, 32))
    if kind == "windows_activation":
        return Episode(kind, length=rng.randint(6, 25), variant=rng.choice(["Notification", "Notification", "Unlicensed"]))
    if kind == "edc_offline":
        return Episode(kind, length=rng.choices([1, 2, 3, 4, 5], weights=[3, 4, 3, 2, 1])[0])
    if kind == "ups_problem":
        variant = rng.choice(["not_detected", "battery"])
        return Episode(kind, length=rng.randint(3, 12) if variant == "not_detected" else rng.randint(6, 13),
                       variant=variant, params={"battery": rng.uniform(52, 62), "rate": rng.uniform(4, 7)})
    if kind == "lan_degraded":
        variant = rng.choices(["bad", "mild", "down"], weights=[5, 3, 1])[0]
        return Episode(kind, length=rng.randint(1, 6), variant=variant,
                       params={"slow": rng.random() < 0.55, "loss": rng.uniform(5.5, 14), "lat": rng.uniform(60, 260)})
    if kind == "disk_smart":
        return Episode(kind, length=rng.randint(6, 20), variant="Caution")
    raise ValueError(kind)


class Simulator:
    """Steps the whole fleet one day at a time. Yields readings and the injected-fault labels."""

    def __init__(self, seed: int = SEED):
        self.rng = random.Random(seed)
        self.stores = build_fleet(self.rng)

    def step(self, day: date) -> tuple[list[dict], list[dict]]:
        rng = self.rng
        rows, truth = [], []
        for store in self.stores:
            # store-level episodes
            if store.missing is None and rng.random() < START_P["missing_pull"]:
                store.missing = Episode("missing_pull", length=rng.choices([1, 2, 3, 4], weights=[5, 3, 2, 1])[0])
            if store.lan is None and len(store.pcs) > 1 and rng.random() < START_P["lan_store"]:
                store.lan = _new_episode("lan_degraded", rng)
                store.lan.variant = "bad"
            missing = store.missing is not None
            for pc in store.pcs:
                labels, row = self._step_pc(pc, store, day)
                for kind in labels:
                    truth.append({"date": day.isoformat(), "store_code": store.code, "pc_id": pc.pc_id, "issue_type": kind})
                if not missing:
                    rows.append(row)
            if missing:
                truth.append({"date": day.isoformat(), "store_code": store.code, "pc_id": None, "issue_type": "missing_pull"})
                store.missing.day += 1
                if store.missing.day >= store.missing.length:
                    store.missing = None
            if store.lan is not None:
                store.lan.day += 1
                if store.lan.day >= store.lan.length:
                    store.lan = None
        return rows, truth

    def _maybe_start(self, pc: PC, kind: str) -> None:
        rng = self.rng
        if kind in pc.episodes:
            return
        if kind == "edc_offline" and not pc.has_edc:
            return
        if kind in pc.pending:
            pc.pending[kind] -= 1
            if pc.pending[kind] <= 0:
                del pc.pending[kind]
                pc.episodes[kind] = _new_episode(kind, rng)
            return
        if rng.random() < START_P[kind]:
            pc.episodes[kind] = _new_episode(kind, rng)

    def _step_pc(self, pc: PC, store: Store, day: date) -> tuple[list[str], dict]:
        rng = self.rng
        for kind in ["overheating", "disk_space", "ram_below_spec", "no_reboot", "windows_activation",
                     "edc_offline", "ups_problem", "lan_degraded", "disk_smart"]:
            self._maybe_start(pc, kind)
        ep = pc.episodes
        labels: list[str] = []

        # temperature
        temp = pc.base_temp + rng.gauss(0, 2.2)
        if "overheating" in ep:
            e = ep["overheating"]
            ramp = min(1.0, e.day / 2)
            temp = e.params["start"] + (e.params["peak"] - e.params["start"]) * ramp + rng.gauss(0, 1.2)
            labels.append("overheating")
        elif rng.random() < NOISE_P["temp_spike"]:
            temp = pc.base_temp + rng.uniform(17, 30)  # busy at pull time, not a fault

        # disk
        pc.disk_used = min(82.0, pc.disk_used + pc.disk_growth * rng.uniform(0.3, 1.7))
        used = pc.disk_used
        if "disk_space" in ep:
            e = ep["disk_space"]
            used = min(99.6, e.params["start"] + e.params["rate"] * e.day)
            labels.append("disk_space")

        ram = pc.ram_spec
        if "ram_below_spec" in ep:
            ram = pc.ram_spec // 2
            labels.append("ram_below_spec")

        # restarts
        if "no_reboot" in ep:
            pc.uptime += 1
            if pc.uptime >= NO_REBOOT_ONSET:
                labels.append("no_reboot")
        elif pc.uptime + 1 >= pc.reboot_every:
            pc.uptime = 0
        else:
            pc.uptime += 1

        activation = "Licensed"
        if "windows_activation" in ep:
            activation = ep["windows_activation"].variant
            labels.append("windows_activation")

        edc = "online" if pc.has_edc else "n/a"
        if "edc_offline" in ep:
            edc = "offline"
            labels.append("edc_offline")
        elif pc.has_edc and rng.random() < NOISE_P["edc_blip"]:
            edc = "offline"  # terminal restarting at pull time

        ups_detected, battery = True, pc.ups_battery + rng.uniform(-1.5, 1.0)
        if "ups_problem" in ep:
            e = ep["ups_problem"]
            labels.append("ups_problem")
            if e.variant == "not_detected":
                ups_detected, battery = False, None
            else:
                battery = max(4.0, e.params["battery"] - e.params["rate"] * e.day)
        elif rng.random() < NOISE_P["ups_blip"]:
            ups_detected, battery = False, None  # USB hiccup during the pull

        link, speed = "up", 1000
        loss, lat = max(0.0, rng.gauss(0.2, 0.25)), max(0.8, rng.gauss(4, 1.6))
        lan_ep = ep.get("lan_degraded") or store.lan
        if lan_ep is not None:
            labels.append("lan_degraded")
            grow = 1 + 0.25 * lan_ep.day
            if lan_ep.variant == "down":
                link, speed, loss, lat = "down", 0, 100.0, None
            elif lan_ep.variant == "bad":
                loss = lan_ep.params["loss"] * grow * rng.uniform(0.85, 1.15)
                lat = lan_ep.params["lat"] * rng.uniform(0.8, 1.2)
                speed = 100 if lan_ep.params["slow"] else 1000
            else:  # mild: easy to miss
                loss, lat = rng.uniform(1.5, 4.5), rng.uniform(25, 90)
                speed = 100 if lan_ep.params["slow"] else 1000
        elif rng.random() < NOISE_P["lan_blip"]:
            loss, lat = rng.uniform(3.5, 9), rng.uniform(20, 140)  # a backup upload at pull time

        smart = "OK"
        if "disk_smart" in ep:
            e = ep["disk_smart"]
            smart = "Bad" if e.day >= 10 else "Caution"
            labels.append("disk_smart")

        pulled_at = datetime.combine(day, time(5, 0)) + timedelta(minutes=rng.randint(0, 40), seconds=rng.randint(0, 59))
        last_boot = (pulled_at - timedelta(days=pc.uptime, hours=rng.uniform(1, 8))).replace(microsecond=0)
        row = {
            "date": day.isoformat(), "store_code": store.code, "pc_id": pc.pc_id, "role": pc.role,
            "pulled_at": pulled_at.isoformat(), "cpu_model": pc.cpu, "cpu_temp_c": round(temp, 1),
            "ram_gb": ram, "ram_spec_gb": pc.ram_spec, "disk_total_gb": pc.disk_total,
            "disk_free_pct": round(100 - used, 1), "os_build": pc.os_build,
            "lan_link": link, "lan_speed_mbps": speed, "packet_loss_pct": round(min(loss, 100.0), 1),
            "latency_ms": None if lat is None else round(lat, 1),
            "last_boot": last_boot.isoformat(), "uptime_days": round((pulled_at - last_boot).total_seconds() / 86400, 1),
            "win_activation": activation, "edc_status": edc,
            "ups_detected": int(ups_detected), "ups_battery_pct": None if battery is None else round(min(battery, 100.0)),
            "smart_status": smart,
        }

        # advance and close episodes
        for kind in list(ep):
            e = ep[kind]
            e.day += 1
            if e.day >= e.length:
                del ep[kind]
                if kind == "no_reboot":
                    pc.uptime = 0
                if kind == "ups_problem" and e.variant == "battery":
                    pc.ups_battery = rng.uniform(95, 100)  # battery replaced
                if kind in ("overheating", "lan_degraded", "edc_offline") and rng.random() < RECUR_P:
                    pc.pending[kind] = rng.randint(2, 6)
        return labels, row


def simulate(start: date, end: date, seed: int = SEED):
    """Yield (day, rows, truth) for every day from start to end inclusive."""
    sim = Simulator(seed)
    for i in range(BURN_IN_DAYS, 0, -1):
        sim.step(start - timedelta(days=i))
    d = start
    while d <= end:
        rows, truth = sim.step(d)
        yield d, rows, truth
        d += timedelta(days=1)


def fleet(seed: int = SEED) -> list[Store]:
    return Simulator(seed).stores
