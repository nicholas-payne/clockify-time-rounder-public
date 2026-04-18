import streamlit as st
import pandas as pd
import numpy as np
import requests
import json
import datetime as dt
import altair as alt
import os

CLOCKIFY_API_KEY = os.getenv("CLOCKIFY_API_KEY")

if not CLOCKIFY_API_KEY:
    raise RuntimeError("CLOCKIFY_API_KEY environment variable not set")

# Accessing workspace data from Clockify first
header = {'X-Api-Key':CLOCKIFY_API_KEY}
r = requests.get(url='https://api.clockify.me/api/v1/user',headers=header)
workspace_id = json.loads(r.text)["activeWorkspace"]

# Streamlit app display header
st.title('Clockify Weekly Time Report with Rounding')
st.subheader('Published by NP')

# Selecting Invoice Date using streamlit date picker
invoice_date = st.date_input(
    "Select Invoice Date",
    'today'
)

# Ensuring Monday is selected or picking the next Monday if needed
invoice_date_week_day = invoice_date.isoweekday()

if invoice_date_week_day > 1:
    true_invoice_date = invoice_date + dt.timedelta(days=8-invoice_date_week_day)
    st.write('Provided date', invoice_date, 'is not a Monday. Invoice Date set forward to the nearest Monday', true_invoice_date)

else:
    true_invoice_date = invoice_date
    st.write("Invoice Date:",invoice_date)

# Calculating date ranges for invoice
start_date = true_invoice_date - dt.timedelta(days=7)
end_date = true_invoice_date - dt.timedelta(days=1)
st.write('Monday of Previous Week:',start_date)

# Pulling reports from clocify using workspace ID and invoice date range
url = f"https://reports.api.clockify.me/v1/workspaces/{workspace_id}/reports/detailed"

headers = {
    "X-Api-Key": CLOCKIFY_API_KEY,
    "Content-Type": "application/json",
}

body = {
    "dateRangeStart": f"{start_date}T00:00:00",
    "dateRangeEnd": f"{end_date}T23:59:59",
    "timeZone": "America/Toronto",
    "detailedFilter": {
        "page": 1,
        "pageSize": 50,
    },
    "startWeek":"MONDAY",
}

response = requests.post(url, headers=headers, data=json.dumps(body))

# Parsing response from clockify post request
df_time_intervals = pd.DataFrame(json.loads(response.text)['timeentries'])
if df_time_intervals.empty:
    st.warning("There are no time entries in this window yet")
    st.stop()

df_time_intervals['Date'] = pd.json_normalize(df_time_intervals['timeInterval'])['start'].str[:10]
df_time_intervals['duration_seconds'] = pd.json_normalize(df_time_intervals['timeInterval'])['duration']

# Creating smaller dataframe with relevant columns to sum times per day
df_durations = df_time_intervals[['Date','duration_seconds']].groupby('Date').sum().reset_index()

days_of_week = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

full_range = pd.date_range(start_date,end_date,freq='D')
df_durations["Date"] = pd.to_datetime(df_durations["Date"], format="%Y-%m-%d")
df_durations = df_durations.set_index('Date').reindex(full_range,fill_value=0)
df_durations['Day'] = days_of_week

# Rounding to the nearest half an hour via 1800 seconds
df_durations['rounded_seconds'] = np.ceil(df_durations['duration_seconds']/1800)*1800
df_durations['rounded_hours'] = df_durations['rounded_seconds']/3600
df_durations = df_durations.reset_index(names='Date')

# Displaying a tidy dataframe, consistent with invoice entry system
df_durations_pretty = df_durations[['Day','Date','rounded_hours']].set_index('Date').copy()
df_durations_pretty.index = df_durations_pretty.index.date
df_durations_pretty.index.name = 'Date'

df_durations_pretty['Pay'] = df_durations_pretty['rounded_hours'] * 50
df_durations_pretty['Pay'] = "$" + df_durations_pretty['Pay'].astype('int').astype('str')

st.write(df_durations_pretty)

# Calculating total hours and pay for display
total_hours = df_durations['rounded_hours'].sum()
total_pay = total_hours*50
st.markdown(f"Total number of hours: :green-badge[{total_hours}]")

total_pay_pretty = '$' + f'{total_pay:.2f}'
st.markdown(f"Total pay: :green-badge[{total_pay_pretty}]")

# Creating a bar chart to show hours per day
bars = (
    alt.Chart(df_durations_pretty)
    .mark_bar()
    .encode(
        x=alt.X('Day:N', title='',sort=days_of_week,axis=alt.Axis(labelAngle=0)),
        y=alt.Y('rounded_hours:Q', title='Rounded Hours')
    )
)

labels = (
    alt.Chart(df_durations_pretty)
    .mark_text(
        color='white',
        fontWeight='bold',
        dy=-10,
        size=14
    )
    .encode(
        x=alt.X("Day:N", sort=days_of_week),
        y=alt.Y("rounded_hours:Q"),
        text=alt.Text("rounded_hours:Q", format="~g")
    )
)

chart = bars + labels

st.altair_chart(chart, width='stretch')