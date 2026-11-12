import streamlit as st
import mysql.connector
import pandas as pd
import plotly.express as px

# ---------------------------------------------------------
# 2. Tạo kết nối CSDL & Caching dữ liệu
# ---------------------------------------------------------
@st.cache_resource
def init_connection():
    return mysql.connector.connect(
        host = "localhost",
        port = 3306,
        database = "saas_ai_db",
        username = "root",
        password = ""
    )

conn = init_connection()

@st.cache_data(ttl=600)
def run_query(query, params=None):
    with conn.cursor(dictionary=True) as cursor:
        cursor.execute(query, params or ())
        result = cursor.fetchall()
    return pd.DataFrame(result)

try:
    date_df = run_query("SELECT MIN(signup_date) as min_date, MAX(signup_date) as max_date FROM customers")
    min_d = date_df['min_date'].iloc[0]
    max_d = date_df['max_date'].iloc[0]
    if pd.isna(min_d) or pd.isna(max_d):
        min_d, max_d = pd.to_datetime("2023-01-01").date(), pd.to_datetime("2026-12-31").date()
    else:
        min_d = pd.to_datetime(min_d).date()
        max_d = pd.to_datetime(max_d).date()
except:
    min_d, max_d = pd.to_datetime("2023-01-01").date(), pd.to_datetime("2026-12-31").date()

date_range = st.sidebar.date_input("Khoảng thời gian đăng ký:", [min_d, max_d])

company_size_list = ["Tất cả", "Startup", "SMB", "Enterprise"]
selected_company_size = st.sidebar.selectbox("Quy mô công ty:", company_size_list)

base_sql = """
    SELECT 
        s.customer_id,
        cu.customer_name,
        p.plan_name,
        cu.signup_date,
        cu.company_size,
        s.status,
        p.monthly_price AS monthly_revenue,
        u.ai_api_cost AS api_cost,
        p.ai_token_limit AS tokens
    FROM subscriptions s
    JOIN customers cu ON s.customer_id = cu.customer_id
    JOIN Plans p ON cu.plan_id = p.plan_id
    JOIN Usagelogs u ON s.customer_id = u.customer_id
    WHERE 1=1
"""
query_params = []

if len(date_range) == 2:
    base_sql += " AND cu.signup_date BETWEEN %s AND %s"
    query_params.append(date_range[0])
    query_params.append(date_range[1])

if selected_company_size  != "Tất cả":
    base_sql += " AND cu.company_size = %s"
    query_params.append(selected_company_size)

df = run_query(base_sql, tuple(query_params) if query_params else None)

if not df.empty:
    col1, col2, col3, col4 = st.columns(4)

    monthly_revenue = df[df['status'].isin(['Active', 'Upgraded'])]['monthly_revenue'].sum()
    churn_rate = df[df['status'].isin(['Churned'])]['customer_id'].count() / df['customer_id'].count() * 100
    net_profit = monthly_revenue - df['api_cost'].sum()
    token_limit = df['tokens'].mean()

    col1.metric( "Tổng doanh thu hàng tháng: ", f"{monthly_revenue:,.0f} USD")
    col2.metric("Churn rate: ", f"{churn_rate:,.0f}%")
    col3.metric("Doanh thu: ", f"{net_profit:,.1f} USD")
    col4.metric("Trung bình số vé hỗ trợ ", f"{token_limit:,.0f}")

    st.markdown("---")
    st.subheader("📊 Trực quan hóa Dữ liệu SaaS & AI")

    # Bố cục 2 cột cho các biểu đồ
    col_chart1, col_chart2 = st.columns(2)

    with col_chart1:
        st.subheader("Xu hướng MRR, Churn Rate")
        df['signup_date'] = pd.to_datetime(df['signup_date'])
        df['month_year'] = df['signup_date'].dt.to_period('M').astype(str)
        
        df_trend = df.groupby('month_year').agg(
            monthly_revenue=('monthly_revenue', lambda x: x[df.loc[x.index, 'status'].isin(['Active', 'Upgraded'])].sum()),
            total_customers=('customer_id', 'count'),
            churned_customers=('status', lambda x: (x == 'Churned').sum())
        ).reset_index()
        
        df_trend['churn_rate'] = (df_trend['churned_customers'] / df_trend['total_customers']) * 100
        
        df_trend['monthly_revenue'] = pd.to_numeric(df_trend['monthly_revenue'], errors='coerce').fillna(0)
        df_trend['churn_rate'] = pd.to_numeric(df_trend['churn_rate'], errors='coerce').fillna(0)
        
        df_trend = df_trend.sort_values('month_year')
        
        fig_line = px.line(
            df_trend, 
            x='month_year', 
            y=['monthly_revenue', 'churn_rate'], 
            markers=True,
            labels={'month_year': 'Tháng', 'value': 'Giá trị', 'variable': 'Chỉ số'},
            title="Xu hướng MRR và Churn Rate theo tháng"
        )
        fig_line.for_each_trace(lambda t: t.update(name = 'MRR ($)' if t.name == 'monthly_revenue' else 'Churn Rate (%)'))
        st.plotly_chart(fig_line, use_container_width=True)

    with col_chart2:
        st.subheader("Token Tiêu Thụ vs Chi Phí API")
        fig_scatter = px.scatter(
            df, 
            x='tokens', 
            y='api_cost', 
            color='plan_name',
            hover_data=['customer_name', 'company_size'],
            labels={'tokens': 'Token tiêu thụ', 'api_cost': 'Chi phí API ($)', 'plan_name': 'Gói dịch vụ'},
            title="Token Tiêu Thụ vs. Chi Phí API AI"
        )
        st.plotly_chart(fig_scatter, use_container_width=True)

    col_chart3, col_chart4 = st.columns(2)

    with col_chart3:
        st.subheader("Lý do Hủy Dịch Vụ")
        df_churn_reason = run_query("""
            SELECT churn_reason, COUNT(*) as count 
            FROM Subscriptions 
            WHERE status = 'Churned' AND churn_reason IS NOT NULL AND churn_reason != ''
            GROUP BY churn_reason
        """)
        fig_bar_churn = px.bar(
            df_churn_reason, 
            x='count', 
            y='churn_reason', 
            orientation='h',
            labels={'count': 'Số lượng khách hàng', 'churn_reason': 'Lý do hủy'},
            title="Các lý do Churn phổ biến nhất"
        )
        fig_bar_churn.update_layout(yaxis={'categoryorder':'total ascending'})
        st.plotly_chart(fig_bar_churn, use_container_width=True)

    with col_chart4:
        st.subheader("Phân bố rủi ro Churn theo quy mô")
        df_size_churn = df.groupby(['company_size', 'status']).size().reset_index(name='count')
        fig_bar_group = px.bar(
            df_size_churn, 
            x='company_size', 
            y='count', 
            color='status', 
            barmode='group',
            labels={'company_size': 'Quy mô công ty', 'count': 'Số lượng', 'status': 'Trạng thái'},
            title="Phân bố Trạng thái theo Quy mô Công ty"
        )
        st.plotly_chart(fig_bar_group, use_container_width=True)

    with st.expander("📄 Xem Bảng Dữ Liệu Chi Tiết & Tải Xuống"):
        st.dataframe(df, use_container_width=True)
        
        csv_data = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Tải xuống dữ liệu (CSV)",
            data=csv_data,
            file_name="ecommerce_sales_data.csv",
            mime="text/csv"
        )
else:
    st.warning("⚠️ Không tìm thấy dữ liệu phù hợp với bộ lọc hiện tại!")
