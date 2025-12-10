# TDN OP Datasets Ontology

## Overview
The TDN Operational Planning (OP) system consists of several interconnected datasets that provide data for resource planning, forecasting, actuals, staff capacities, and cost factors. The ontology describes the relationships, entities, and attributes among these datasets, including nuances like geographic splits, variances, and operational implications.

## Datasets

### 1. tdn_plan_demand.csv
- **Description**: Contains planned effort (hours) for projects across TDN subunits, locations, and months.
- **Key Entities**:
  - Project (PID, Project Name, Product Line, Product Segment)
  - Org Unit (e.g., TDNA, TDNC)
  - Org Subunit (e.g., TDNA1, TDNC1)
  - Location (e.g., Hannover (DE), Chennai (IN))
  - Monthly Hours (Jan_25 to Dec_26)
- **Relationships**:
  - Projects are associated with Org Subunit and Location.
  - Hours are planned per month for each project.
- **Nuances**: Same PID appears per subunit for geographic splits (e.g., PID 27529 spans Bern, Hannover, Auburn Hills, Chennai, Shanghai with distinct 2025/26 profiles).

### 2. tdn_actuals.csv
- **Description**: Contains actual effort invested in projects by subunits, locations, and periods.
- **Key Entities**:
  - Project (PID, Project Name)
  - Org Subunit
  - Location
  - Period (e.g., 2025-03)
  - Hours (actual)
- **Relationships**:
  - Links to tdn_plan_demand.csv via PID, Org Subunit, Location, Period for variance analysis.
  - Provides actual data to compare against plans.
- **Nuances**: Actuals track delivered hours per project, location, and month (Jan–Jun 2025), enabling direct variance checks (e.g., repeated Hannover entries for PID 31307).

### 3. tdn_staff.csv
- **Description**: Contains staff capacities for subunits, locations, and months.
- **Key Entities**:
  - Staff (PID for staff)
  - Org Subunit
  - Location
  - Monthly Capacity (Jan_26 to Dec_26)
- **Relationships**:
  - Links to tdn_plan_demand.csv via Org Subunit and Location for capacity planning.
  - Used to assess if planned hours exceed staff capacity.
- **Nuances**: Lists named resources, future months (Jan–Dec 2026) and recurring 120.76 h/month “Confirm 2026” allocations by subunit, mirroring the project hierarchy (e.g., TDNA and TDNA1 cadres, TDNE2 cohort).

### 4. tdn_forecast.csv
- **Description**: Contains forecasting data for future months based on actuals.
- **Key Entities**:
  - Year
  - Type of hours (e.g., Actual plan in DDB, Actuals, FC 1+11)
  - Mapping OrgUnit (e.g., Connectivity & Data)
  - Mapping Sub Unit (e.g., TDNC1, TDNI)
  - Monthly Hours (January to December)
- **Relationships**:
  - Links to tdn_actuals.csv via subunits and periods for trend-based forecasting.
  - Used for future planning and scenario analysis.
- **Nuances**: Provides monthly aggregates filtered to Connectivity & Data/TDNC; includes actuals to June, DDB plan, rolling forecasts (1+11, 2+10, 3+9) and OP 0+12 scenarios; explicit filter note excludes other org units.

### 5. tdn_cost_factor.csv
- **Description**: Contains cost factors for locations in Euros.
- **Key Entities**:
  - Location (DIV CVS Location)
  - Cost Factor (CVS 2025, CVS 2026 Est)
- **Relationships**:
  - Links to all other datasets via Location for cost calculations.
  - Used to compute budget variances and cost hotspots.
- **Nuances**: Supply 2025 and 2026 charge-out multipliers per location, establishing the bridge from hours to cost (e.g., Hannover 96.5/97.71, Shanghai 61.72/57.06, Bern 114.85/144.38).

## Key Relationships and Ontology

- **Project-Subunit-Location**: Projects in tdn_plan_demand.csv are tied to Org Subunit and Location, which link to staff capacities in tdn_staff.csv and cost factors in tdn_cost_factor.csv.
- **Plan-Actual-Variance**: tdn_plan_demand.csv and tdn_actuals.csv are linked by PID, Org Subunit, Location, Period to calculate variances.
- **Forecast-Actual**: tdn_forecast.csv uses actuals from tdn_actuals.csv for subunits to predict future hours.
- **Staff-Capacity**: tdn_staff.csv provides capacities for subunits and locations, used to check against planned hours in tdn_plan_demand.csv.
- **Cost-Budget**: Cost factors from tdn_cost_factor.csv are applied to hours from other datasets to calculate costs and variances.
- **Hierarchical Structure**: TDN Division > Org Unit > Org Subunit > Teams (e.g., TDNA > TDNA1, TDNA2).

## Cross-Dataset Links & Variances

- **Variances**: Many projects exceed Jan–Jun baseline (e.g., Hyper Accurate AI Fuel Sensing planned ~170 h/month in Chennai but logs 130–330 h/month across sites, ~3.6k hour overrun YTD; Battery‑eHDT driving range prediction 260/300 h plan vs. 100–320 h actuals, ~2.2k extra hours).
- **Underspends**: Projects like TDNL_PI‑Management budget 360–397 h per site but only ~24 h posted, signalling major underspend and possible cancellation.
- **Cost Impacts**: Actuals concentrate in high-cost hubs (e.g., Hannover postings with 96.5 €/h, Shanghai with 61.72 €/h), enabling cost roll-ups.
- **Forecast Alignment**: Forecast confirms Connectivity & Data consumed 3.45k–3.95k hours per month through June and rolls forward DDB plan; filtered to TDNC, additional extracts needed for other org units.
- **Staff Blind Spots**: 2026 staffing aligns with subunit names, but some projects (e.g., TDNP2) consume hours without 2025 plan baseline, highlighting planning gaps.