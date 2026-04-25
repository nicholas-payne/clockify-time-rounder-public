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
# RATE = os.getenv("RATE")

# Start date needs to be specified since the new method is biweekly reporting
new_method_start_date = dt.datetime.strptime("2026-03-01","%Y-%m-%d").date()
RATE = 50 #placeholder

if not CLOCKIFY_API_KEY:
    raise RuntimeError("CLOCKIFY_API_KEY environment variable not set")

# Accessing workspace data from Clockify first
header = {'X-Api-Key':CLOCKIFY_API_KEY}
r = requests.get(url='https://api.clockify.me/api/v1/user',headers=header)
workspace_id = json.loads(r.text)["activeWorkspace"]

# Streamlit app display header
st.title('Clockify Weekly Time Report with Rounding')

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
        st.write(
            'Provided date', 
            invoice_date, 
            'is not a', 
            target_day_name,
            '. Invoice Date set forward to: ', 
            true_inv)
    
    return true_inv,target_day_name

def biweekly_from_start_checker(inv_date: dt.date, new_method_start_date: dt.date):
    '''
    Checks the invoice date to see if it aligns within the biweekly cadence from the start date
    '''
    days_from_biweekly = (inv_date - new_method_start_date).days % 14
    days_to_biweekly = 14 - days_from_biweekly

    if days_from_biweekly == 0:
        true_inv_biweekly = inv_date
        st.write("Submission Deadline: ", inv_date)
    else:
        true_inv_biweekly = inv_date + dt.timedelta(days = days_to_biweekly)
        st.write(
            'Provided date', 
            inv_date, 
            'is not on the biweekly schedule. Reporting Date set forward to: ', 
            true_inv_biweekly)

    return true_inv_biweekly

def extract_times_from_clockify(true_inv_date: dt.date,display_days:int):
    '''
    Queries the Clockify API to pull all time entries in the previous {display_days} days from {true_inv_date}
    '''
    
    start_date = true_inv_date - dt.timedelta(days=display_days)
    end_date = true_inv_date - dt.timedelta(days=1)

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
        }
    }

    response = requests.post(url, headers=headers, data=json.dumps(body))

    return response, start_date, end_date

def create_durations_df(api_response,start_date,end_date,invoice_days):

    df_time_intervals = pd.DataFrame(json.loads(response.text)['timeentries'])
    if df_time_intervals.empty:
        st.warning("There are no time entries in this window yet")
        st.stop()

    df_time_intervals['Date'] = pd.json_normalize(df_time_intervals['timeInterval'])['start'].str[:10]
    df_time_intervals['duration_seconds'] = pd.json_normalize(df_time_intervals['timeInterval'])['duration']

    days_of_week = ([calendar.day_name[(start_date + dt.timedelta(days=x)).isoweekday()-1] for x in range(invoice_days)])
    full_range = pd.date_range(start_date,end_date,freq='D')
    
    df_durations = df_time_intervals[['Date','duration_seconds']].groupby('Date').sum().reset_index()
    df_durations["Date"] = pd.to_datetime(df_durations["Date"], format="%Y-%m-%d")
    df_durations = df_durations.set_index('Date').reindex(full_range,fill_value=0)
    df_durations["Date_display"] = [date.strftime("%a %b %d") for date in full_range]
    df_durations['Day'] = days_of_week

    # Rounding to the nearest half an hour via 1800 seconds
    df_durations['rounded_seconds'] = np.ceil(df_durations['duration_seconds']/1800)*1800
    df_durations['rounded_hours'] = df_durations['rounded_seconds']/3600
    df_durations = df_durations.reset_index(names='Date')

    return df_durations, days_of_week

def make_bar_chart(df_durations:pd.DataFrame,invoice_days:int):
    bars = (
        alt.Chart(df_durations)
        .mark_bar(size=25*14/invoice_days)
        .encode(
            x=alt.X('Date_display:N', title='',sort=alt.SortField(field='Date', order='ascending'),axis=alt.Axis(labelAngle=0)),
            y=alt.Y('rounded_hours:Q', title='Rounded Hours')
        )
    )

    labels = (
        alt.Chart(df_durations)
        .mark_text(
            color='white',
            fontWeight='bold',
            dy=-10,
            size=14
        )
        .encode(
            x=alt.X('Date_display:N', title='',sort=alt.SortField(field='Date', order='ascending'),axis=alt.Axis(labelAngle=0)),
            y=alt.Y("rounded_hours:Q"),
            text=alt.Text("rounded_hours:Q", format="~g")
        )
    )

    chart = bars + labels

    st.altair_chart(chart, width='stretch')

if method == 'Old method':

    # Ensuring the specified invoice DOW is selected or picking the next applicable date if needed
    invoice_days = 7
    invoice_day_of_week = 1
    true_invoice_date,true_invoice_week_day = day_of_week_checker(invoice_date,invoice_day_of_week)

    # Extract time entries from Clockify
    response, start_date, end_date = extract_times_from_clockify(true_invoice_date,invoice_days)
    st.write(true_invoice_week_day,'of Previous Week:',start_date)

    df_durations, days_of_week = create_durations_df(response, start_date, end_date, invoice_days)

    # Displaying a clean dataframe, consistent with invoice entry system
    df_durations_pretty = df_durations[['Day','Date','rounded_hours']].set_index('Date').copy()
    df_durations_pretty.index = df_durations_pretty.index.date
    df_durations_pretty.index.name = 'Date'

    df_durations_pretty['Pay'] = df_durations_pretty['rounded_hours'] * RATE
    df_durations_pretty['Pay'] = "$" + df_durations_pretty['Pay'].astype('int').astype('str')

    # st.dataframe(df_durations_pretty,height='content')
    st.dataframe(df_durations_pretty,height='content')

    # Calculating total hours and pay for display
    total_hours = df_durations['rounded_hours'].sum()
    total_pay = total_hours*RATE
    st.markdown(f"Total number of hours: :green-badge[{total_hours}]")

    total_pay_pretty = '$' + f'{total_pay:.2f}'
    st.markdown(f"Total pay: :green-badge[{total_pay_pretty}]")


    # Creating a bar chart to show hours per day
    make_bar_chart(df_durations,invoice_days)

elif method == 'New method':

    # Ensuring SUNDAY is selected and the date aligns with a biweekly payroll cadence
    true_invoice_date = biweekly_from_start_checker(
        invoice_date,
        new_method_start_date)

        # Ensuring the specified invoice DOW is selected or picking the next applicable date if needed
    invoice_days = 14

    # Extract time entries from Clockify
    response, start_date, end_date = extract_times_from_clockify(true_invoice_date,invoice_days)

    df_durations, days_of_week = create_durations_df(response, start_date, end_date, invoice_days)

    # Displaying a clean dataframe, consistent with invoice entry system
    df_durations_pretty = df_durations[['Date_display','rounded_hours']].set_index('Date_display').copy()
    # df_durations_pretty.index = df_durations_pretty.index.date
    df_durations_pretty.index.name = 'Date'
    df_durations_pretty.rename(columns={'rounded_hours':'Hours'},inplace=True)

    df_durations_pretty['Pay'] = df_durations_pretty['Hours'] * RATE
    df_durations_pretty['Pay'] = "$" + df_durations_pretty['Pay'].astype('int').astype('str')

    start_time = 9
    df_durations_pretty['Start Time'] = f'{start_time}:00 am'
    df_durations_pretty['End Time'] = start_time + df_durations_pretty['Hours']
    
    def decimal_to_time_str(x):
        hours = int(x)
        if hours > 12:
            hours_display = hours - 12
            am_pm = 'pm'
        else:
            hours_display = hours
            am_pm = 'am'

        minutes = int((x - hours) * 60)
        t = f"{hours_display}:{minutes:02d} {am_pm}"

        return t

    df_durations_pretty['End Time'] = df_durations_pretty['End Time'].apply(decimal_to_time_str)

    st.dataframe(df_durations_pretty,height='content')

    # Calculating total hours and pay for display
    total_hours = df_durations['rounded_hours'].sum()
    total_pay = total_hours*RATE
    st.markdown(f"Total number of hours: :green-badge[{total_hours}]")

    total_pay_pretty = '$' + f'{total_pay:.2f}'
    st.markdown(f"Total pay: :green-badge[{total_pay_pretty}]")


    # Creating a bar chart to show hours per day
    make_bar_chart(df_durations,invoice_days)


    

    



