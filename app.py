from flask import Flask, jsonify, request
from flask_cors import CORS
import os
import sqlite3
from datetime import datetime, timedelta
import json

app = Flask(__name__)
CORS(app)

# ========================================
# CONFIGURAÇÃO DO BANCO DE DADOS
# ========================================

# Tenta usar PostgreSQL, se falhar usa SQLite
DATABASE_URL = os.environ.get('DATABASE_URL', '')

def get_db_connection():
    """Conecta ao banco de dados (PostgreSQL ou SQLite)"""
    if DATABASE_URL:
        try:
            import psycopg2
            return psycopg2.connect(DATABASE_URL)
        except ImportError:
            print("⚠️ psycopg2 não instalado, usando SQLite")
            return sqlite3.connect('database.db')
    else:
        return sqlite3.connect('database.db')

def init_db():
    """Cria tabelas se não existirem (SQLite)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Verifica se é SQLite
    if not DATABASE_URL:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS vendas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente_id INTEGER,
                produto_id INTEGER,
                total REAL,
                status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS clientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT,
                ativo BOOLEAN DEFAULT 1
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS produtos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT,
                ativo BOOLEAN DEFAULT 1
            )
        ''')
        
        # Dados de exemplo para teste
        cursor.execute("SELECT COUNT(*) FROM clientes")
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO clientes (nome) VALUES ('Cliente Exemplo 1'), ('Cliente Exemplo 2')")
            cursor.execute("INSERT INTO produtos (nome) VALUES ('Produto A'), ('Produto B'), ('Produto C')")
            cursor.execute("""
                INSERT INTO vendas (cliente_id, produto_id, total, status, created_at) 
                VALUES 
                (1, 1, 150.00, 'concluído', datetime('now', '-1 day')),
                (2, 2, 299.90, 'pendente', datetime('now', '-2 hours')),
                (1, 3, 75.50, 'concluído', datetime('now', '-5 hours'))
            """)
        
        conn.commit()
    
    conn.close()

# ========================================
# ENDPOINTS DO DASHBOARD
# ========================================

@app.route('/api/dashboard')
def get_dashboard():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if DATABASE_URL:
            # PostgreSQL
            cursor.execute("SELECT COALESCE(SUM(total), 0) FROM vendas")
            total_sales = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM produtos")
            total_products = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM clientes")
            active_clients = cursor.fetchone()[0]
            
            cursor.execute("SELECT COALESCE(SUM(total), 0) FROM vendas WHERE DATE(created_at) = CURRENT_DATE")
            today_sales = cursor.fetchone()[0]
            
            cursor.execute("""
                SELECT DATE_TRUNC('month', created_at) as mes, COALESCE(SUM(total), 0) as total
                FROM vendas 
                WHERE created_at >= NOW() - INTERVAL '12 months'
                GROUP BY mes
                ORDER BY mes
            """)
            monthly_data = cursor.fetchall()
        else:
            # SQLite
            cursor.execute("SELECT COALESCE(SUM(total), 0) FROM vendas")
            total_sales = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM produtos")
            total_products = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM clientes")
            active_clients = cursor.fetchone()[0]
            
            cursor.execute("SELECT COALESCE(SUM(total), 0) FROM vendas WHERE DATE(created_at) = DATE('now')")
            today_sales = cursor.fetchone()[0]
            
            cursor.execute("""
                SELECT strftime('%m', created_at) as mes, COALESCE(SUM(total), 0) as total
                FROM vendas 
                WHERE created_at >= DATE('now', '-12 months')
                GROUP BY mes
                ORDER BY mes
            """)
            monthly_data = cursor.fetchall()
        
        # Processa dados mensais
        monthly_sales = [0] * 12
        for row in monthly_data:
            try:
                # SQLite retorna mês como string, PostgreSQL como datetime
                if isinstance(row[0], str):
                    mes_index = int(row[0]) - 1
                else:
                    mes_index = row[0].month - 1
                monthly_sales[mes_index] = float(row[1] or 0)
            except:
                pass
        
        # Últimas vendas
        cursor.execute("""
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
            ORDER BY v.created_at DESC
            LIMIT 10
        """)
        recent_sales = cursor.fetchall()
        
        recent_sales_list = []
        for row in recent_sales:
            recent_sales_list.append({
                'id': row[0],
                'cliente': row[1],
                'produto': row[2],
                'valor': float(row[3] or 0),
                'status': row[4] or 'concluído',
                'data': row[5].isoformat() if row[5] else None
            })
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'totalSales': float(total_sales or 0),
            'totalProducts': int(total_products or 0),
            'activeClients': int(active_clients or 0),
            'todaySales': float(today_sales or 0),
            'monthlySales': monthly_sales,
            'recentSales': recent_sales_list
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# ========================================
# ENDPOINTS INDIVIDUAIS
# ========================================

@app.route('/api/sales/total')
def get_total_sales():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COALESCE(SUM(total), 0) FROM vendas")
        total = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        return jsonify(float(total or 0))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/count')
def get_products_count():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM produtos")
        count = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        return jsonify(int(count or 0))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/clients/active')
def get_active_clients():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM clientes")
        count = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        return jsonify(int(count or 0))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sales/today')
def get_today_sales():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if DATABASE_URL:
            cursor.execute("SELECT COALESCE(SUM(total), 0) FROM vendas WHERE DATE(created_at) = CURRENT_DATE")
        else:
            cursor.execute("SELECT COALESCE(SUM(total), 0) FROM vendas WHERE DATE(created_at) = DATE('now')")
        total = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        return jsonify(float(total or 0))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sales/monthly')
def get_monthly_sales():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if DATABASE_URL:
            cursor.execute("""
                SELECT DATE_TRUNC('month', created_at) as mes, COALESCE(SUM(total), 0) as total
                FROM vendas 
                WHERE created_at >= NOW() - INTERVAL '12 months'
                GROUP BY mes
                ORDER BY mes
            """)
        else:
            cursor.execute("""
                SELECT strftime('%m', created_at) as mes, COALESCE(SUM(total), 0) as total
                FROM vendas 
                WHERE created_at >= DATE('now', '-12 months')
                GROUP BY mes
                ORDER BY mes
            """)
        data = cursor.fetchall()
        cursor.close()
        conn.close()
        
        monthly = [0] * 12
        for row in data:
            try:
                if isinstance(row[0], str):
                    mes_index = int(row[0]) - 1
                else:
                    mes_index = row[0].month - 1
                monthly[mes_index] = float(row[1] or 0)
            except:
                pass
        
        return jsonify(monthly)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sales/recent')
def get_recent_sales():
    limit = request.args.get('limit', 10, type=int)
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
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
            ORDER BY v.created_at DESC
            LIMIT %s
        """ if DATABASE_URL else """
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
            ORDER BY v.created_at DESC
            LIMIT ?
        """, (limit,))
        sales = cursor.fetchall()
        cursor.close()
        conn.close()
        
        result = []
        for row in sales:
            result.append({
                'id': row[0],
                'cliente': row[1],
                'produto': row[2],
                'valor': float(row[3] or 0),
                'status': row[4] or 'concluído',
                'data': row[5].isoformat() if row[5] else None
            })
        
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ========================================
# INICIALIZAÇÃO
# ========================================

if __name__ == '__main__':
    init_db()  # Cria tabelas se não existirem
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
