import streamlit as st
import pandas as pd
import numpy as np
import requests
import json
import datetime as dt
import altair as alt
import os
import calendar

from api_key import CLOCKIFY_API_KEY

# CLOCKIFY_API_KEY = os.getenv("CLOCKIFY_API_KEY")
# NEW_METHOD_START = os.getenv("NEW_METHOD_START")

# Start date needs to be specified since the new method is biweekly reporting
NEW_METHOD_START_DATE = dt.datetime.strptime("2026-03-01","%Y-%m-%d").date()

if not CLOCKIFY_API_KEY:
    raise RuntimeError("CLOCKIFY_API_KEY environment variable not set")

# Accessing workspace data from Clockify first
header = {'X-Api-Key':CLOCKIFY_API_KEY}
r = requests.get(url='https://api.clockify.me/api/v1/user',headers=header)
workspace_id = json.loads(r.text)["activeWorkspace"]

# Streamlit app display header
st.title('Clockify Weekly Time Report with Rounding')
st.subheader('Published by NP')

method = st.radio(
    "Select the report type",
    ["New method",'Old method'],
    captions=[
        "Biweekly billing with specified EOD time",
        "Weekly billing swith specified daily hours"
    ]
)

# Selecting Invoice Date using streamlit date picker
invoice_date = st.date_input(
    "Select Invoice Date",
    'today'
)

def day_of_week_checker(inv_date: dt.date, target_iso_day: int):
    '''
    Checks the input date for day of the week and compares to the target day of the week. 1=Monday, ..., 7=Sunday
    Returns the true invoice date rolled forward

    '''
    inv_date_week_day = inv_date.isoweekday()
    target_day_name = calendar.day_name[target_iso_day-1]

    days = (target_iso_day - inv_date_week_day) % 7

    if days == 0:
        true_inv = inv_date
        st.write("Invoice Date:",true_inv)

    else:
        true_inv = inv_date + dt.timedelta(days=days)
        st.write('Provided date', invoice_date, 'is not a', target_day_name,'. Invoice Date set forward to: ', true_inv)
    
    return true_inv,target_day_name


if method == 'Old method':
    # This method currently only works for Mondays with Monday-Sunday invoicing

    # Ensuring Monday is selected or picking the next Monday if needed
    true_invoice_date,true_invoice_week_day = day_of_week_checker(invoice_date,1)

    # Calculating date ranges for invoice
    start_date = true_invoice_date - dt.timedelta(days=7)
    end_date = true_invoice_date - dt.timedelta(days=1)
    st.write(true_invoice_week_day,'of Previous Week:',start_date)

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

elif method == 'New method':

    # Ensuring SUNDAY is selected and the date aligns with a biweekly payroll cadence
    true_invoice_date,true_invoice_week_day = day_of_week_checker(invoice_date,7)

