#!/usr/bin/env python
# coding: utf-8

# In[5]:


import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import requests
import os
from datetime import datetime
import streamlit as st

# Function to fetch options data
def fetch_options_data(stock_symbol):
    session = requests.Session()
    url = f'https://www.nseindia.com/api/option-chain-indices?symbol={stock_symbol}'

    headers = {
        'User-Agent': 'Mozilla/5.0',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://www.nseindia.com/',
        'X-Requested-With': 'XMLHttpRequest',
    }

    response = session.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        if 'records' in data and 'data' in data['records']:
            calls_data, puts_data = [], []
            for option in data['records']['data']:
                strike_price = option['strikePrice']
                expiry_date = option['expiryDate']
                if 'CE' in option:
                    calls_data.append({'strikePrice': strike_price, 'expiryDate': expiry_date, **option['CE']})
                if 'PE' in option:
                    puts_data.append({'strikePrice': strike_price, 'expiryDate': expiry_date, **option['PE']})
            calls_df = pd.DataFrame(calls_data) if calls_data else pd.DataFrame()
            puts_df = pd.DataFrame(puts_data) if puts_data else pd.DataFrame()
            return calls_df, puts_df
    return None, None

# Classify options based on spot price
def classify_options(options_df, spot_price):
    options_df = options_df[options_df['impliedVolatility'] > 0]  # Filter out zero IVs
    options_df['moneyness'] = 'OTM'
    options_df.loc[options_df['strikePrice'] == spot_price, 'moneyness'] = 'ATM'

    # For calls
    options_df.loc[options_df['strikePrice'] < spot_price, 'moneyness'] = 'ITM'  # Calls ITM
    options_df.loc[options_df['strikePrice'] > spot_price, 'moneyness'] = 'OTM'  # Calls OTM

    return options_df

# Calculate implied volatility skew
def calculate_volatility_skew(options_df):
    filtered_df = options_df[options_df['impliedVolatility'] > 0]
    if filtered_df.empty:
        return None, None

    # Group by expiry date
    grouped_df = filtered_df.groupby('expiryDate')
    skew_data = []

    for expiry, group in grouped_df:
        # Calculate the ATM implied volatility for the current expiry group
        atm_iv = group.loc[group['moneyness'] == 'ATM', 'impliedVolatility'].mean()

        # If ATM IV is available, calculate skew
        if pd.notna(atm_iv):
            group = group.copy()  # Avoid SettingWithCopyWarning
            group['skew'] = group['impliedVolatility'] - atm_iv
            group['ATM_IV'] = atm_iv  # Add ATM IV to the group
            skew_data.append(group[['strikePrice', 'moneyness', 'expiryDate', 'impliedVolatility', 'skew', 'ATM_IV']])

    return pd.concat(skew_data), atm_iv

# Load baseline skew from CSV if it exists
def load_baseline_skew(filename):
    if os.path.exists(filename):
        return pd.read_csv(filename)
    return None

# Save baseline skew to CSV
def save_baseline_skew(baseline_skew, filename):
    if baseline_skew is not None:
        baseline_skew.to_csv(filename, index=False)

# Compare current and baseline skews
def compare_skews(baseline_skew, current_skew, threshold):
    if baseline_skew is None or current_skew is None:
        return None

    # Merge current and baseline skews on strikePrice and expiryDate
    merged_skew = current_skew.merge(baseline_skew, on=['strikePrice', 'expiryDate'], suffixes=('_current', '_baseline'))

    # Calculate the changes only for ATM strikes
    merged_skew['ATM_IV_change'] = merged_skew['impliedVolatility_current'] - merged_skew['impliedVolatility_baseline']
    merged_skew['skew_change'] = merged_skew['skew_current'] - merged_skew['skew_baseline']

    # Filter for ATM strikes to calculate ATM_IV_change
    atm_changes = merged_skew[merged_skew['moneyness_current'] == 'ATM']

    # Identify significant changes based on the threshold
    significant_changes = atm_changes[
        (atm_changes['ATM_IV_change'].abs() > threshold) | 
        (atm_changes['skew_change'].abs() > threshold)
    ]

    if not significant_changes.empty:
        return significant_changes[['strikePrice', 'expiryDate', 'ATM_IV_change', 'skew_change']]
    
    return None

# Plot volatility skew using Streamlit's plotting features
def plot_volatility_skew(df, option_type):
    st.subheader(f'Volatility Skew for {option_type}')
    fig, ax = plt.subplots(figsize=(10, 6))

    # Get unique expiry dates and sort them
    sorted_expiry_dates = sorted(df['expiryDate'].unique(), key=pd.to_datetime)
    
    # Check if the dataframe is empty
    if df.empty:
        st.write(f"No data available for {option_type}.")
        return
    
    for expiry in sorted_expiry_dates:
        subset = df[df['expiryDate'] == expiry]
        if not subset.empty:  # Only plot if there are entries
            ax.plot(subset['strikePrice'], subset['impliedVolatility'], label=f'Expiry: {expiry}')
    
    ax.set_xlabel('Strike Price')
    ax.set_ylabel('Implied Volatility')
    ax.legend()
    ax.grid()
    st.pyplot(fig)

# Display significant changes
def display_significant_changes(changes, option_type):
    if changes is None:
        st.write(f"No significant changes for {option_type}.")
    else:
        st.write(f"Significant change in {option_type} ATM IV and Skew:")
        for _, row in changes.iterrows():
            st.write(f"- Strike Price: {row['strikePrice']}, Expiry Date: {row['expiryDate']}")
            st.write(f"  - ATM IV Change: {row['ATM_IV_change']:.2f}%")
            st.write(f"  - Skew Change: {row['skew_change']:.2f}%")

# Save significant changes to a CSV file
def save_significant_changes_to_file(significant_changes, option_type):
    date_str = datetime.now().strftime('%Y-%m-%d')
    filename = f'significant_changes_{option_type}_{date_str}.csv'
    changes_df = significant_changes.copy()  # Ensure it's a DataFrame
    changes_df.to_csv(filename, index=False)
    st.write(f"Significant changes saved to {filename}")

# Streamlit dashboard logic
def main():
    st.title('Options Volatility Skew Dashboard')

    # Sidebar for stock symbol, threshold, and spot price input
    stock_symbol = st.sidebar.text_input("Stock Symbol", value="NIFTY")
    threshold = st.sidebar.slider("Significant Change Threshold (in %)", 1, 10, 5) / 100
    spot_price = 24800  # Static spot price

    # Load baseline skews
    baseline_calls_filename = "baseline_calls_skew.csv"
    baseline_puts_filename = "baseline_puts_skew.csv"
    baseline_calls = load_baseline_skew(baseline_calls_filename)
    baseline_puts = load_baseline_skew(baseline_puts_filename)

    # Initialize significant changes
    significant_call_changes = None
    significant_put_changes = None

    # Tabs for different functionalities
    tab1, tab2 = st.tabs(["Volatility Skew", "Significant Changes"])

    # Tab for fetching and plotting volatility skew
    with tab1:
        st.write(f"Fetching options data for {stock_symbol}...")
        calls, puts = fetch_options_data(stock_symbol)

        if calls is not None and puts is not None:
            # Classify options based on spot price
            calls = classify_options(calls, spot_price)
            puts = classify_options(puts, spot_price)

            # Calculate volatility skew
            calls_data, calls_atm_iv = calculate_volatility_skew(calls)
            puts_data, puts_atm_iv = calculate_volatility_skew(puts)

            # Plot skews
            plot_volatility_skew(calls_data, 'Calls')
            plot_volatility_skew(puts_data, 'Puts')

            # Compare skews and display significant changes
            st.subheader("Comparing Skews")
            significant_call_changes = compare_skews(baseline_calls, calls_data, threshold)
            significant_put_changes = compare_skews(baseline_puts, puts_data, threshold)

            # Save significant changes to files
            if significant_call_changes is not None:
                save_significant_changes_to_file(significant_call_changes, 'Calls')
            if significant_put_changes is not None:
                save_significant_changes_to_file(significant_put_changes, 'Puts')

            # Save the current skews as the new baseline
            save_baseline_skew(calls_data, baseline_calls_filename)
            save_baseline_skew(puts_data, baseline_puts_filename)

        else:
            st.write("Failed to fetch options data.")

    # Tab for displaying significant changes
    with tab2:
        display_significant_changes(significant_call_changes, 'Calls')
        display_significant_changes(significant_put_changes, 'Puts')

if __name__ == "__main__":
    main()


# In[ ]:




