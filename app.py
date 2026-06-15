from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
import psycopg2
import psycopg2.extras
import os
import re
import time
import json
import io
from datetime import datetime

app = Flask(__name__)
CORS(app)

# ============================================================
# CACHE SIMPLES EM MEMÓRIA
# ============================================================
_cache = {}
CACHE_TTL = 28800

def cache_get(key):
    if key in _cache:
        valor, timestamp = _cache[key]
        if time.time() - timestamp < CACHE_TTL:
            return valor
    return None

def cache_set(key, valor):
    _cache[key] = (valor, time.time())

def cache_clear():
    _cache.clear()

# ============================================================
# CONEXÃO COM BANCO DE DADOS
# ============================================================
def get_conn():
    last_err = None
    for attempt in range(3):
        try:
            conn = psycopg2.connect(
                host            = os.environ.get('DB_HOST'),
                port            = int(os.environ.get('DB_PORT', 5432)),
                database        = os.environ.get('DB_NAME', 'railway'),
                user            = os.environ.get('DB_USER'),
                password        = os.environ.get('DB_PASS'),
                sslmode         = 'require',
                connect_timeout = 10,
                keepalives      = 1,
                keepalives_idle    = 30,
                keepalives_interval = 10,
                keepalives_count   = 5,
            )
            return conn
        except Exception as e:
            last_err = e
            time.sleep(0.5 * (attempt + 1))
    raise last_err

def _serializar_row(row):
    import datetime as dt
    out = {}
    for k, v in row.items():
        if isinstance(v, dt.date):
            try:
                out[k] = v.isoformat()
            except Exception:
                out[k] = None
        else:
            out[k] = v
    return out

def consultar(sql, params=()):
    conn   = get_conn()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute(sql, params)
    rows = []
    while True:
        try:
            row = cursor.fetchone()
            if row is None:
                break
            rows.append(_serializar_row(dict(row)))
        except Exception:
            continue
    cursor.close()
    conn.close()
    return rows

# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================
def montar_filtros(args):
    condicoes = []
    params    = []

    anos = args.getlist('ano')
    if anos:
        placeholders = ','.join(['%s'] * len(anos))
        condicoes.append(f"ano IN ({placeholders})")
        params.extend([int(a) for a in anos])

    meses = args.getlist('mes')
    if meses:
        placeholders = ','.join(['%s'] * len(meses))
        condicoes.append(f"mes IN ({placeholders})")
        params.extend([int(m) for m in meses])

    unidade = args.get('unidade')
    if unidade:
        condicoes.append("unidade = %s")
        params.append(unidade)

    uf = args.get('uf')
    if uf:
        condicoes.append("uf = %s")
        params.append(uf)

    tipo = args.get('tipo')
    if tipo:
        condicoes.append("tipo_operacao = %s")
        params.append(tipo)

    marca = args.get('marca')
    if marca:
        condicoes.append("marca = %s")
        params.append(marca)

    vendedores = args.getlist('vendedor')
    if vendedores:
        placeholders = ','.join(['%s'] * len(vendedores))
        condicoes.append(f"vendedor IN ({placeholders})")
        params.extend(vendedores)

    where = ("WHERE " + " AND ".join(condicoes)) if condicoes else ""
    return where, params

def cache_key(rota, args):
    return rota + '?' + '&'.join(f'{k}={v}' for k, v in sorted(args.items()))

def _aquecer_cache():
    import threading
    def _warm():
        try:
            conn   = get_conn()
            cursor = conn.cursor()
            def q(sql):
                cursor.execute(sql)
                return [r[0] for r in cursor.fetchall()]
            filtros = {
                'anos':       q("SELECT DISTINCT ano FROM faturamento WHERE ano IS NOT NULL AND ano > 0 ORDER BY ano DESC"),
                'meses':      q("SELECT DISTINCT mes FROM faturamento WHERE mes IS NOT NULL AND mes > 0 ORDER BY mes"),
                'unidades':   q("SELECT DISTINCT unidade FROM faturamento WHERE unidade IS NOT NULL ORDER BY unidade"),
                'ufs':        q("SELECT DISTINCT uf FROM faturamento WHERE uf IS NOT NULL AND uf != '' ORDER BY uf"),
                'marcas':     q("SELECT DISTINCT marca FROM faturamento WHERE marca IS NOT NULL ORDER BY marca"),
                'tipos':      q("SELECT DISTINCT tipo_operacao FROM faturamento WHERE tipo_operacao IS NOT NULL ORDER BY tipo_operacao"),
                'vendedores': q("SELECT DISTINCT vendedor FROM faturamento WHERE vendedor IS NOT NULL ORDER BY vendedor"),
            }
            cache_set('filtros', filtros)
            cursor.close()
            conn.close()
            print("Cache aquecido com sucesso!")
        except Exception as e:
            print(f"Erro cache warmup: {e}")
    threading.Thread(target=_warm, daemon=True).start()

_aquecer_cache()

# ============================================================
# ROTAS PRINCIPAIS
# ============================================================
@app.route('/')
def home():
    return jsonify({"status": "online", "mensagem": "API Átomo funcionando!"})

@app.route('/api/filtros')
def filtros():
    key    = 'filtros'
    cached = cache_get(key)
    if cached: return jsonify(cached)

    conn   = get_conn()
    cursor = conn.cursor()

    def q(sql):
        cursor.execute(sql)
        return [r[0] for r in cursor.fetchall()]

    resultado = {
        'anos':       q("SELECT DISTINCT ano  FROM faturamento WHERE ano  IS NOT NULL AND ano > 0 ORDER BY ano DESC"),
        'meses':      q("SELECT DISTINCT mes  FROM faturamento WHERE mes  IS NOT NULL AND mes > 0 ORDER BY mes"),
        'unidades':   q("SELECT DISTINCT unidade FROM faturamento WHERE unidade IS NOT NULL ORDER BY unidade"),
        'ufs':        q("SELECT DISTINCT uf   FROM faturamento WHERE uf   IS NOT NULL AND uf != '' ORDER BY uf"),
        'marcas':     q("SELECT DISTINCT marca FROM faturamento WHERE marca IS NOT NULL ORDER BY marca"),
        'tipos':      q("SELECT DISTINCT tipo_operacao FROM faturamento WHERE tipo_operacao IS NOT NULL ORDER BY tipo_operacao"),
        'vendedores': q("SELECT DISTINCT vendedor FROM faturamento WHERE vendedor IS NOT NULL ORDER BY vendedor"),
    }
    cursor.close()
    conn.close()
    cache_set(key, resultado)
    return jsonify(resultado)

@app.route('/api/dashboard')
def dashboard():
    key    = cache_key('dashboard', dict(request.args))
    cached = cache_get(key)
    if cached: return jsonify(cached)

    where, params = montar_filtros(request.args)
    and_or = 'AND' if where else 'WHERE'

    conn   = get_conn()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def run(sql, p):
        cursor.execute(sql, p)
        return [_serializar_row(dict(r)) for r in cursor.fetchall()]

    kpis = run(f"""
        SELECT
            ROUND(CAST(SUM(CASE WHEN tipo_operacao='Venda' THEN valor_nf ELSE 0 END) AS NUMERIC),2) AS faturamento,
            ROUND(CAST(SUM(CASE WHEN tipo_operacao='Devolucao' THEN valor_nf ELSE 0 END) AS NUMERIC),2) AS devolucoes,
            ROUND(CAST(SUM(CASE WHEN tipo_operacao='Bonificacao' THEN valor_nf ELSE 0 END) AS NUMERIC),2) AS bonificacoes,
            ROUND(CAST(SUM(CASE WHEN tipo_operacao='Venda' THEN valor_nf ELSE 0 END)/NULLIF(COUNT(CASE WHEN tipo_operacao='Venda' THEN 1 END),0) AS NUMERIC),2) AS ticket_medio,
            COUNT(DISTINCT cliente) AS total_clientes,
            COUNT(CASE WHEN tipo_operacao='Venda' THEN 1 END) AS qtd_vendas
        FROM faturamento {where}
    """, params)

    mensal = run(f"""
        SELECT ano, mes