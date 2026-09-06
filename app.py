from flask import Flask, jsonify, request
from flask_cors import CORS
import psycopg2
import os
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)

# Configuração do banco de dados (Railway PostgreSQL)
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://user:pass@localhost/db')

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

# ========================================
# ENDPOINTS DO DASHBOARD
# ========================================

@app.route('/api/dashboard')
def get_dashboard():
    """Endpoint principal que retorna todos os dados do dashboard"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # 1. Total de vendas
        cur.execute("SELECT COALESCE(SUM(total), 0) FROM vendas WHERE status != 'cancelado'")
        total_sales = cur.fetchone()[0]
        
        # 2. Total de produtos
        cur.execute("SELECT COUNT(*) FROM produtos WHERE ativo = true")
        total_products = cur.fetchone()[0]
        
        # 3. Clientes ativos
        cur.execute("SELECT COUNT(*) FROM clientes WHERE ativo = true")
        active_clients = cur.fetchone()[0]
        
        # 4. Vendas de hoje
        cur.execute("""
            SELECT COALESCE(SUM(total), 0) 
            FROM vendas 
            WHERE DATE(created_at) = CURRENT_DATE
        """)
        today_sales = cur.fetchone()[0]
        
        # 5. Vendas por mês (últimos 12 meses)
        cur.execute("""
            SELECT 
                DATE_TRUNC('month', created_at) as mes,
                COALESCE(SUM(total), 0) as total
            FROM vendas 
            WHERE created_at >= NOW() - INTERVAL '12 months'
            GROUP BY mes
            ORDER BY mes
        """)
        monthly_sales_data = cur.fetchall()
        
        # Preenche meses sem vendas com 0
        monthly_sales = [0] * 12
        for row in monthly_sales_data:
            mes_index = row[0].month - 1
            monthly_sales[mes_index] = float(row[1])
        
        # 6. Últimas vendas
        cur.execute("""
            SELECT 
                v.id,
                c.nome as cliente,
                p.nome as produto,
                v.total as valor,
                v.status,
                v.created_at as data
            FROM vendas v
            JOIN clientes c ON v.cliente_id = c.id
            JOIN produtos p ON v.produto_id = p.id
            WHERE v.status != 'cancelado'
            ORDER BY v.created_at DESC
            LIMIT 10
        """)
        recent_sales = cur.fetchall()
        
        recent_sales_list = []
        for row in recent_sales:
            recent_sales_list.append({
                'id': row[0],
                'cliente': row[1],
                'produto': row[2],
                'valor': float(row[3]),
                'status': row[4],
                'data': row[5].isoformat() if row[5] else None
            })
        
        cur.close()
        conn.close()
        
        return jsonify({
            'totalSales': float(total_sales),
            'totalProducts': int(total_products),
            'activeClients': int(active_clients),
            'todaySales': float(today_sales),
            'monthlySales': monthly_sales,
            'recentSales': recent_sales_list
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ========================================
# ENDPOINTS INDIVIDUAIS (fallback)
# ========================================

@app.route('/api/sales/total')
def get_total_sales():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(SUM(total), 0) FROM vendas WHERE status != 'cancelado'")
        total = cur.fetchone()[0]
        cur.close()
        conn.close()
        return jsonify(float(total))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/count')
def get_products_count():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM produtos WHERE ativo = true")
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        return jsonify(int(count))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/clients/active')
def get_active_clients():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM clientes WHERE ativo = true")
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        return jsonify(int(count))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sales/today')
def get_today_sales():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT COALESCE(SUM(total), 0) 
            FROM vendas 
            WHERE DATE(created_at) = CURRENT_DATE
        """)
        total = cur.fetchone()[0]
        cur.close()
        conn.close()
        return jsonify(float(total))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sales/monthly')
def get_monthly_sales():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                DATE_TRUNC('month', created_at) as mes,
                COALESCE(SUM(total), 0) as total
            FROM vendas 
            WHERE created_at >= NOW() - INTERVAL '12 months'
            GROUP BY mes
            ORDER BY mes
        """)
        data = cur.fetchall()
        cur.close()
        conn.close()
        
        monthly = [0] * 12
        for row in data:
            mes_index = row[0].month - 1
            monthly[mes_index] = float(row[1])
        
        return jsonify(monthly)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sales/recent')
def get_recent_sales():
    limit = request.args.get('limit', 10, type=int)
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                v.id,
                c.nome as cliente,
                p.nome as produto,
                v.total as valor,
                v.status,
                v.created_at as data
            FROM vendas v
            JOIN clientes c ON v.cliente_id = c.id
            JOIN produtos p ON v.produto_id = p.id
            WHERE v.status != 'cancelado'
            ORDER BY v.created_at DESC
            LIMIT %s
        """, (limit,))
        sales = cur.fetchall()
        cur.close()
        conn.close()
        
        result = []
        for row in sales:
            result.append({
                'id': row[0],
                'cliente': row[1],
                'produto': row[2],
                'valor': float(row[3]),
                'status': row[4],
                'data': row[5].isoformat() if row[5] else None
            })
        
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ========================================
# INICIALIZAÇÃO
# ========================================

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
