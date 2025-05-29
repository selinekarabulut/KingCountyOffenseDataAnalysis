import pandas as pd
import geopandas as gpd
import os
import zipfile
import requests
from io import BytesIO
import plotly.express as px
from dash import Dash, dcc, html, Input, Output
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# -------------------------------------
# Load and clean crime data
# -------------------------------------
url = "https://data.kingcounty.gov/api/views/4kmt-kfqf/rows.csv?accessType=DOWNLOAD"
df = pd.read_csv(url, low_memory=False)
df["incident_datetime"] = pd.to_datetime(df["incident_datetime"], errors="coerce")

# Filter out anything before a reasonable threshold (e.g., Jan 2020)
df = df[df["incident_datetime"] >= pd.Timestamp("2020-01-01")]
df = df.dropna(subset=["zip", "nibrs_code_name", "incident_datetime"])
df["zip"] = df["zip"].astype(str).str.zfill(5)
df["Month_Year"] = df["incident_datetime"].dt.to_period("M").astype(str)
df["hour"] = df["incident_datetime"].dt.hour


# -------------------------------------
# Load ZIP shapefile and filter to relevant ZIPs
# -------------------------------------

shapefile_url = "https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_zcta520_500k.zip"
shapefile_dir = "shapefiles"

# Download and extract if not already
if not os.path.exists(shapefile_dir):
    os.makedirs(shapefile_dir, exist_ok=True)
    r = requests.get(shapefile_url, verify=False)
    z = zipfile.ZipFile(BytesIO(r.content))
    z.extractall(shapefile_dir)

# Load shapefile
zip_geo = gpd.read_file(os.path.join(shapefile_dir, "cb_2020_us_zcta520_500k.shp"))
zip_geo["zip"] = zip_geo["ZCTA5CE20"]
zip_geo = zip_geo[zip_geo["zip"].isin(df["zip"].unique())]

# -------------------------------------
# Prepare dropdown options
# -------------------------------------
month_options = sorted(df["Month_Year"].dropna().unique(), key=lambda x: pd.Period(x, freq='M'))
crime_options = sorted(df["nibrs_code_name"].unique())

# -------------------------------------
# Build Dash App
# -------------------------------------
app = Dash(__name__)
app.layout = html.Div([
    html.H2("King County Crime Map by ZIP Code"),

    html.Label("Select Crime Type:"),
    dcc.Dropdown(
        id="crime-dropdown",
        options=[{"label": crime, "value": crime} for crime in crime_options],
        value="LARCENY/THEFT"
    ),

    html.Label("Select Month-Year:"),
    dcc.Dropdown(
        id="month-dropdown",
        options=[{"label": m, "value": m} for m in month_options],
        value=month_options[0]
    ),

    dcc.Graph(id="zip-map"),

    html.H3("Monthly Trend for Selected Crime Type"),
    dcc.Graph(id="trend-line"),

    html.H3("Hourly Trend for Selected Crime Type"),
    dcc.Graph(id="hourly-line")
])



@app.callback(
    Output("zip-map", "figure"),
    Input("crime-dropdown", "value"),
    Input("month-dropdown", "value")
)
def update_map(selected_crime, selected_month):
    # Aggregate crime counts by ZIP
    agg = df[
        (df["nibrs_code_name"] == selected_crime) &
        (df["Month_Year"] == selected_month)
    ].groupby("zip").size().reset_index(name="count")

    # Merge with ZIP geometries
    merged = zip_geo.merge(agg, on="zip", how="left")
    merged["count"] = merged["count"].fillna(0)

    # Generate choropleth
    fig = px.choropleth_mapbox(
        merged,
        geojson=merged.geometry.__geo_interface__,
        locations=merged.index,
        color="count",
        hover_name="zip",
        hover_data={"count": True, "zip": True},
        mapbox_style="open-street-map",
        center={"lat": 47.5, "lon": -122.1},
        zoom=7,
        opacity=0.6,
        color_continuous_scale="Reds",
        height=600
    )
    fig.update_layout(margin={"r":0,"t":30,"l":0,"b":0})
    fig.update_traces(marker_line_width=1.5, marker_line_color='black')
    return fig

@app.callback(
    Output("trend-line", "figure"),
    Input("crime-dropdown", "value")
)
def update_trend(selected_crime):
    trend = (
        df[df["nibrs_code_name"] == selected_crime]
        .groupby("Month_Year")
        .size()
        .reset_index(name="count")
        .sort_values("Month_Year")
    )

    fig = px.line(
        trend,
        x="Month_Year",
        y="count",
        title=f"Monthly Trend for {selected_crime}",
        markers=True
    )
    fig.update_layout(xaxis_title="Month", yaxis_title="Number of Incidents")
    return fig

@app.callback(
    Output("hourly-line", "figure"),
    Input("crime-dropdown", "value")
)
def update_hourly_trend(selected_crime):
    hourly = (
        df[df["nibrs_code_name"] == selected_crime]
        .groupby("hour")
        .size()
        .reset_index(name="count")
        .sort_values("hour")
    )

    fig = px.line(
        hourly,
        x="hour",
        y="count",
        title=f"Hourly Crime Pattern: {selected_crime}",
        markers=True
    )
    fig.update_layout(
        xaxis=dict(dtick=1, title="Hour of Day (0–23)"),
        yaxis_title="Number of Incidents"
    )
    return fig


if __name__ == "__main__":
    app.run_server(debug=True, port=8051)
