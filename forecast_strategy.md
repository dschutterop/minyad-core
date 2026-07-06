# Forecast-strategie achter de dashboardgrafiek — analyse

**Status:** analyse/beoordelingsdocument, geen spec. Geschreven op basis van de codebase op
`main` (laatste commit `fb0dab0`, "Add market signal support to v3 planner").
**Doel:** in kaart brengen welke forecast-methodiek daadwerkelijk de grafieklijn in het
dashboard (`/dashboard` en `/history`) opbouwt, zodat dit gericht beoordeeld en zo nodig
aangepast kan worden.

---

## Bevinding vooraf

Minyad heeft **twee volledig gescheiden forecast-systemen**. De geavanceerde, zelflerende
LP-planner (strategy v3, zie [`strategy_v3.md`](strategy_v3.md)) die de batterij daadwerkelijk
aanstuurt, is **niet** de bron van de grafieklijn in het dashboard. Die grafiek wordt gevoed
door een eenvoudiger, losstaand mechanisme in `api/main.py` en `frontend/main.py`.

Hieronder eerst dat dashboard-mechanisme (waar de vraag om vroeg), daarna ter vergelijking het
"echte" strategy-v3-forecastsysteem, en tot slot de geconstateerde inconsistenties tussen
beide.

---

## Deel 1 — Wat de dashboardgrafiek daadwerkelijk tekent

### 1.1 Solar-forecastlijn ("forecast")

- Bron: rechtstreeks Open-Meteo, `direct_radiation` + `diffuse_radiation` + `shortwave_radiation`,
  per uur (`api/main.py:1616-1661`, functie `fetch_open_meteo_forecast`).
- Coördinaten en piekvermogen zijn losse env-vars: `FORECAST_LATITUDE=51.9788`,
  `FORECAST_LONGITUDE=4.3158`, `SOLAR_PEAK_W=5000` (`api/main.py:185-188`) — dit zijn **andere
  waarden** dan de v3-planner gebruikt (51.97 / 4.31, zie `minyad/strategy/v3/forecast_client.py:11-12`).
- Omrekening naar Watt: `scale_to_system()` — `(direct + diffuse) / 1000 × SOLAR_PEAK_W × 0.80`
  (`api/main.py:1607-1609`). Vaste efficiëntiefactor (`SOLAR_FORECAST_EFFICIENCY = 0.80`), geen
  kalibratie op historische opbrengst.
- Resultaat wordt weggeschreven in tabel `solar_forecast_points`, ververst zodra de laatste
  fetch ouder is dan 20 minuten (`api/main.py:1695-1702`, `ensure_recent_solar_forecast`).
- `/dashboard/curves` leest deze tabel voor het gevraagde venster, interpoleert naar de juiste
  stapgrootte (`interpolate_points`) en geeft dit terug als veld `forecast`
  (`api/main.py:1781-1801`).

### 1.2 Batterijlijn ("battery_forecast") — pure heuristiek

`extrapolate_battery_curve()` (`api/main.py:1721-1738`) berekent per forecastpunt een verwacht
batterijvermogen met **vaste drempels**, los van instellingen, prijzen of verbruiksprofiel:

```
capacity_wh = 10000                      # hardcoded, niet battery.capacity_wh (=10240)
als solar_w > 1200 en batterij niet vol  → laden:    -min(2500, (solar_w - 1200) × 0.6)
elif solar_w < 400 en batterij > 15%     → ontladen:  min(1200, 400 - solar_w)
anders                                    → 0 (standby)
```

(Sign-conventie: positief = ontladen, negatief = laden — consistent met de GoodWe-telemetrie-
conventie uit `strategy_v3.md` §1.)

- Startpunt is de **live SoC** uit de laatste MQTT-status, niet de geplande SoC-trajectory.
- Geen verbruiksforecast, geen prijzen, geen SoC-vloer/-plafond uit settings, geen
  Vrijdag-full-cycle-regel, geen zelflerende PV-kalibratiefactor.
- Het is in feite een projectie puur voor visualisatie; het levert geen input aan enige
  regelloop en wordt door niets anders gelezen dan het dashboard zelf.

### 1.3 Rendering in het dashboard

- `/dashboard/curves?window=...&offset=...` levert `forecast`, `battery_forecast` en de
  gemeten `series` (solar/battery/grid/household) (`api/main.py:1741-1803`).
- De frontend haalt dit op via `loadCurves()` / `loadHistory()` en tekent de lijnen zelf als
  SVG-paths (`drawChart()` voor de dagweergave op het hoofddashboard, `draw()` voor de
  history-pagina) — puur client-side lijnstuk-interpolatie tussen datapunten, geen extra
  forecastlogica (`frontend/main.py:1592-1614`, `frontend/main.py:1683`).
- De batterijlijn op het scherm is een merge van gemeten historie + de heuristische
  `battery_forecast` (`frontend/main.py:1602`, `frontend/main.py:1676`).

---

## Deel 2 — Het "echte" forecastsysteem (strategy v3), niet gekoppeld aan de grafiek

Dit is het systeem beschreven in `strategy_v3.md` en geïmplementeerd in `minyad/strategy/v3/`,
dat de batterij daadwerkelijk aanstuurt (of in shadow-mode meedraait naast v2):

1. **Rolling LP-planner** (`minyad/strategy/v3/planner.py`) — elke 15 minuten een lineair
   programma (PuLP/CBC) over 96 slots (24 uur) dat `pv_forecast`, `load_forecast` en prijzen
   combineert tot een SoC-traject, met een curtailment-variabele, solar-only-laadgate,
   Vrijdag-full-cycle als zachte constraint en een terminal-SoC-conditie.
2. **PV-forecast**: Open-Meteo `shortwave_radiation`, vermenigvuldigd met een **zelflerende
   kalibratiefactor** die dagelijks wordt herberekend uit 14 dagen werkelijke Enphase-opbrengst
   versus bestraling (`minyad/strategy/v3/forecast_client.py:103-108`, `calibrate_pv_factor`).
3. **Verbruiksforecast**: gemiddeld historisch verbruik per 15-minuten-slot over 14 dagen
   (`minyad/strategy/v2/consumption_profile.py`), hergebruikt uit v2.
4. **Prijzen**: sinds de laatste commit (`fb0dab0`, "Add market signal support to v3 planner")
   via een genormaliseerd `market_signal`-kanaal (`price_vector`) met prioriteit en
   geldigheidsvenster, met terugval op het oudere ENTSO-E-payload en daarna op vaste prijzen
   (`minyad/strategy/v3/price_client.py`) — deze uitbreiding is nog niet bijgewerkt in
   `strategy_v3.md`.
5. **Trajectory tracker** vertaalt de afwijking tussen actuele en geplande SoC naar een
   sturingsbias en dynamische vloer/plafond voor de guard.
6. Publiceert het plan op MQTT-topic `minyad/strategy/plan` en een surplusforecast op
   `minyad/strategy/surplus_forecast` (bedoeld voor Vesper) — **geen van beide topics wordt
   gelezen door `api/main.py` of `frontend/main.py`** (geverifieerd: nul treffers op
   `slot_plan`, `SlotPlan`, `strategy/plan`, `soc_target`, `surplus_forecast` in beide
   bestanden).

---

## Samengevat: waar zit de mismatch

| Aspect | Dashboardgrafiek (wat je ziet) | Strategy v3 planner (wat de batterij stuurt) |
|---|---|---|
| PV-forecast | Ruwe Open-Meteo-straling × vaste factor (0.80 × 5000 W piek) | Zelflerende kalibratiefactor uit 14 dagen echte opbrengst |
| Verbruik | Niet meegenomen | 14-dagen historisch profiel per 15-min-slot |
| Prijzen | Alleen los getoond (ENTSO-E-staafjes), niet verwerkt in de forecastlijn | Volwaardige LP-optimalisatie + market-signal-kanaal |
| Batterijgedrag | Vaste drempels (1200 W / 400 W), losse `capacity_wh = 10000` | LP-geoptimaliseerd traject, `battery.capacity_wh = 10240`, SoC-vloer/plafond/Vrijdagregel |
| Locatie/instellingen | Eigen env-vars (`FORECAST_LATITUDE/LONGITUDE/SOLAR_PEAK_W`) | Eigen constanten in `forecast_client.py` (net iets andere coördinaten) |

Dit betekent: de lijn die operators nu op het dashboard zien als "verwachte batterij/zon-curve"
weerspiegelt **niet** wat de v3-strategie daadwerkelijk plant of doet. Er zijn feitelijk twee
parallelle, losgekoppelde en onderling inconsistente forecast-implementaties in de codebase.

---

## Openstaande vraag voor de beoordeling

Als het doel is de methodiek te verbeteren, is de kernvraag: moet de dashboardgrafiek de
bestaande `slot_plans` / `minyad/strategy/plan`-data gaan tonen — er is al een rijke databron
beschikbaar via `SlotPlan.soc_target_pct`, `pv_forecast_w`, `load_forecast_w`, `price_import` —
in plaats van dat `extrapolate_battery_curve` een eigen, losstaande heuristiek blijft
gebruiken?

Secundaire punten om mee te nemen in de beoordeling:
- De licht verschillende locatie-coördinaten en losstaande piekvermogen-/efficiëntie-constanten
  tussen `api/main.py` en `minyad/strategy/v3/forecast_client.py`.
- De hardcoded `capacity_wh = 10000` in `extrapolate_battery_curve` versus de instelbare
  `battery.capacity_wh` (default 10240) in strategy v3.
- Of de recente market-signal-uitbreiding (`fb0dab0`) nog verwerkt moet worden in
  `strategy_v3.md`, dat deze wijziging nog niet documenteert.
