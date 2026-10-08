# Candidate datasets to extend coverage beyond NAD r24

For review before any integration. Compiled 2026-10-07 from three research passes
(`data/research/coverage/*.md`, which hold the per-source evidence, quoted licence text,
live counts and scripts). Row counts are the source's own; overlap with NAD and between city
and county sources is not removed, and parcel-derived sources overstate addresses.

Licence classes: **PD** public domain or CC0; **PD-law** no licence text but a public record
under state law; **permissive** reuse granted without attribution; **waiver** attribution
licence with an OSM waiver on record; **CC BY** attribution required (OSM needs a waiver);
**none** nothing stated; **restricted** redistribution limited or sold.

## Policy

Only sources explicitly in bounds for OSM are integrated: a waiver or permission recorded on
the OSM wiki or community forum, or a CC0, public-domain or PDDL licence stated by the
publisher. "Public record under state law", "none stated" and OpenAddresses' licence labels
do not qualify. The tiers below are kept for reference; this section is what the policy
allows.

### In bounds under the policy

| Source | Rows | Clearance | Still to confirm before integration |
|---|---:|---|---|
| San Diego County (SanGIS) | 1.22M | OSM wiki import page records explicit SanGIS, city and county permission | Re-read the wiki page and the current SanGIS end-user agreement |
| City of Los Angeles address points | 1.05M | CC0 on the item | |
| Fresno County | 399K | CC0 in the item licence | |
| San Francisco (EAS) | 389K | PDDL on the Socrata dataset | |
| New Orleans site address points | 269K | CC0 per OpenAddresses | Open the data.nola.gov dataset page and confirm CC0 is stated there |
| Chester County PA (Esri Community Maps snapshot) | 222K | CC BY 4.0 with Esri's OSM waiver in the item licence; OSM wiki `Import/Chester_County` | 2021 data |
| Jefferson Parish LA | 179K | OSM wiki `Import/Catalogue/Jefferson Parish Addresses and Buildings` records email permission | Permission covers OSM use; confirm it is not limited to the original import |
| Forsyth County and Hinesville GA (Esri snapshots) | 121K | CC BY 4.0 with Esri's OSM waiver | 2021 data |
| Lackawanna County PA | 97K | PDDL | 2017 data |
| City of Charleston SC | 58K | Public domain under the city's open data policy | |
| Puerto Rico 2014 standardized addresses (archived) | 126K | Public domain, verified from an archived data.pr.gov page | Stale and only three municipios; low value |

About 4.0M rows. Two more are unencumbered in substance but not labelled CC0 or public
domain, so they need your call: **Oakland County MI** (559K; terms grant copying,
distribution and adaptation with no attribution clause) and **San Mateo County** (270K; a
general site statement that its information "is considered in the public domain").

### Out of bounds under the policy (largest first)

Florida DOR statewide (8.7M, public record by law only), the South Carolina (2.9M) and
Missouri (1.1M) statewide files (none stated), all "none stated" county and city layers in
Tier 2, Hillsborough FL and DeKalb GA (CC BY, no waiver yet), Colorado OIT (attribution
required), Athens-Clarke GA (emailed permission not found on the wiki), Detroit (CC0 claimed
by OpenAddresses only), and Hawaii, Nevada, Mississippi and Michigan beyond Oakland County.
Of these, the ones a single permission or waiver would unlock are listed under "Decisions
needed" below.

## Where NAD r24 falls short

| State | Kept rows | 2020 housing units | Coverage | Note |
|---|---:|---:|---:|---|
| FL | 42K | 9.87M | 0.4% | Holmes and Jackson counties only |
| GA | 205K | 4.41M | 4.6% | Atlanta only |
| SC | 212K | 2.35M | 9.1% | York and Oconee only |
| ID | 89K | 0.75M | 11.8% | 6 counties |
| CA | 2.52M | 14.39M | 17.5% | 49 of 58 counties absent |
| PA | 1.06M | 5.74M | 18.5% | 57 of 67 counties absent |
| LA | 427K | 2.07M | 20.6% | 60 parishes absent |
| SD | 86K | 0.40M | 21.8% | 61 counties absent |
| MO | 1.70M | 2.80M | 60.5% | 90 counties absent, incl. St. Louis city |
| MI, MS, NV, NH, HI, PR | 0 | 4.57M, 1.32M, 1.28M, 0.64M, 0.56M, 1.60M | 0% | absent entirely |

Every other state is above 80%; the remaining gaps are single counties (listed in the
"other partial states" report).

## Tier 1: usable now (licence verified against the publisher)

| Source | Rows | Licence | Notes |
|---|---:|---|---|
| Florida DOR Master Address List (statewide) | 8.7M with coordinates | PD-law (public record; *Microdecisions v. Skinner*) | Postal city and ZIP always filled; street parts split; **no units**; positions are parcel centroids or geocodes, median 23–51 m from NAD/county points; 10% of rows have no coordinates; republished every six months |
| City of Los Angeles address points | 1.05M | PD (CC0) | |
| San Diego County (SanGIS) | 1.22M | permissive, OSM permission on record | |
| Fresno County | 399K | PD (CC0) | |
| San Francisco | 389K | PD (PDDL) | |
| San Mateo County | 270K | PD statement | |
| Oakland County MI site addresses | 559K | permissive, no attribution clause | Largest clean Michigan source |
| Chester County PA (Esri Community Maps snapshot) | 222K | waiver (CC BY 4.0 + OSM waiver) | 2021 data; the county's own current layer is restricted |
| Jefferson Parish LA | 179K | none, OSM permission by email | |
| New Orleans site address points | 110K | PD (CC0) | Licence from OpenAddresses' field; portal page not opened |
| Forsyth County and Hinesville GA (Esri snapshots) | 121K | waiver | Forsyth snapshot is from 2021 |
| Lackawanna County PA | 97K | PD (PDDL) | 2017 copy |
| City of Charleston SC | small | PD (open data policy) | |

Total of this tier: roughly 13M rows, 8.7M of them Florida.

## Tier 2: large, but the licence is "none stated" or rests on a public-records argument

These need either a policy decision (treat state public records as usable, as the OSM wiki
does for Florida and California) or written permission from the publisher.

| Source | Rows | Status | Notes |
|---|---:|---|---|
| South Carolina statewide NG911 (OpenAddresses upload, Nov 2025) | 2.88M (~2.5M distinct) | none; origin inferred to be the state 911 office | Would take SC from 9% to near complete |
| Missouri statewide (911 Service Board, Sunshine Law release) | 1.11M new | none (public record) | Covers mostly the counties NAD lacks; St. Louis city (134K parcels) separate |
| Philadelphia address points | 954K | none | The real point layer, not OpenAddresses' parcel table |
| Allegheny County PA | 663K | none | Biggest Pennsylvania win if permission is given |
| MARIS county address points, Mississippi (24 live counties) | ~600K | none; 2010 email permission quoted on the OSM wiki | 42 counties have parcels only |
| Nevada: Washoe County, Henderson, rural counties | ~630K | none (disclaimers) | Clark County outside Henderson sells its data; no clean source |
| Detroit address points | 487K | PD per OpenAddresses only | Not verified on the city's page |
| Fulton County GA (outside Atlanta) | ~285K new | none ("as is") | |
| Milwaukee County WI | 302K | terms of use, reference only | Milwaukee is 43% covered in NAD |
| Johnson County KS | 304K | likely restricted (inferred from AIMS sales model) | |
| Hawaii: Honolulu, Hawaii, Maui, Kauai counties | ~408K | Honolulu requires a credit notice; others none | Whether Honolulu's open-data terms cover the hosted layer is unconfirmed |
| Louisiana parishes via OpenAddresses (Lafayette, Calcasieu, others) | ~480K | mostly none | St. Tammany and Ouachita forbid redistribution |
| Idaho counties (Canyon, Bonneville, Bannock, Bonner, …) | ~400K | none | Ada County (275K) says "do not re-distribute" despite OpenAddresses' CC BY label |
| California disclaimer-only counties (Sacramento, Alameda, Santa Clara, Riverside, …) | several million | none; `Template:PD-CAGov` argument | Riverside includes utility meters; some sources are parcel layers with owner data |
| Rapid City / Pennington SD | 63K | none | The statewide host is dead |
| Government of Guam NG911 | 34K | none | Not in NAD or OpenAddresses |

## Tier 3: attribution required (needs an OSM waiver)

| Source | Rows | Licence |
|---|---:|---|
| Hillsborough County FL | 754K | CC BY 4.0 (stated; conflicts with the Florida public-records rule) |
| DeKalb County GA | 389K | CC BY 4.0; a waiver request is already pending in the OSM community |
| Colorado OIT Public Addresses (current) | 275K new | attribution required, no resale (OpenAddresses' "Public Domain" label is wrong) |
| Athens-Clarke County GA | 78K | CC BY 4.0; imported to OSM in 2022 on emailed permission |

## Do not use

- **New Hampshire:** E911 address data is excluded from public records by RSA 106-H:14. Only parcel points exist.
- **LA County CAMS (2.69M):** "Data not to be used for sending mail or navigation."
- **Restricted or sold:** Bucks, Lancaster, Berks, Luzerne, Butler, Lehigh, Northampton (PA); Gwinnett, Cobb, Augusta, Macon-Bibb, Forsyth's own layer (GA); San Luis Obispo (CA); Clark County (NV); SEMCOG (MI, rights assigned back); St. Tammany, Ouachita (LA).
- **Share-alike:** Sonoma County CA (CC BY-SA 3.0).
- **Wrong kind of data:** Idaho "statewide" (Esri reverse-geocoded building footprints); 21 Georgia small-county OpenAddresses files scraped from qPublic map tiles; parcel layers with owner names (Chatham, Douglas, Bartow GA; El Dorado, Imperial, San Joaquin CA).
- **Dead or withdrawn:** Kern CA, Champaign IL, South Dakota statewide host, Puerto Rico (data.pr.gov removed; a 2014 three-municipio archive survives).

## Decisions needed before integration

1. **Public-records policy.** Whether a state public record with no licence text (Florida DOR, South Carolina and Missouri statewide files, the California disclaimer-only counties) is acceptable. The OSM wiki already takes that position for Florida and California; it is the single decision that moves the most rows.
2. **Stated CC BY versus public-records law** (Hillsborough FL): which prevails.
3. **Permission requests** worth sending: Allegheny PA, Philadelphia, Fulton/Gwinnett/Cobb GA, Johnson KS, Detroit, Washoe NV, Honolulu.
4. **US Virgin Islands:** NAD's 2,852 "Proposed" St John rows appear to be assigned-but-unsigned addresses; a per-source exception would publish them.
5. **Florida position quality:** DOR points are parcel centroids. Use county E911 layers where their licence allows (Miami-Dade 1.16M is CC0 per OpenAddresses, unverified; Palm Beach, Orange, Lee, Duval, Pinellas, Broward state nothing) and DOR elsewhere.

## Integration notes

- Each source needs its own field mapping; most carry a full street string rather than NAD's components, so the expansion rules would run on the whole name.
- Overlap with NAD must be deduplicated (Missouri's statewide file overlaps on some counties; city and county sources overlap each other).
- Provenance must be carried per row so a source can be withdrawn if its terms change.
- Freshness varies from live services to 2017 snapshots; the published tileset should say which.
