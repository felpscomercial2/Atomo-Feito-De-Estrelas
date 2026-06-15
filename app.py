from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
import psycopg2
import psycopg2.extras
import os
import re
import time
import json
import io

app = Flask(__name__)
CORS(app)

# ============================================================
# CACHE SIMPLES EM MEMÓRIA
# Guarda resultados por 5 minutos para não bater no banco
# toda vez que alguém acessa a página
# ============================================================
_cache = {}
CACHE_TTL = 28800  # 8 horas em segundos

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
# CONEXÃO COM SUPABASE
# ============================================================
def get_conn():
    # Tenta conectar até 3 vezes — Supabase pode fechar conexões idle
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
    import datetime
    out = {}
    for k, v in row.items():
        if isinstance(v, datetime.date):
            try:
                out[k] = v.isoformat()
            except Exception:
                out[k] = None  # data inválida no banco (ex: ano 20256) → ignora
        else:
            out[k] = v
    return out

def consultar(sql, params=()):
    conn   = get_conn()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute(sql, params)
    # Lê linha a linha para não quebrar em datas inválidas
    rows = []
    while True:
        try:
            row = cursor.fetchone()
            if row is None:
                break
            rows.append(_serializar_row(dict(row)))
        except Exception:
            continue  # pula linha com data inválida e segue
    cursor.close()
    conn.close()
    return rows

# ============================================================
# MONTA FILTROS
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

# ============================================================
# ROTAS
# ============================================================
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
            cursor2 = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor2.execute("SELECT DISTINCT produto, cod_produto, marca FROM faturamento WHERE produto IS NOT NULL AND produto != '' ORDER BY produto")
            produtos = [_serializar_row(dict(r)) for r in cursor2.fetchall()]
            cache_set('todos_produtos', produtos)
            cursor.close(); cursor2.close(); conn.close()
            print("Cache aquecido com sucesso!")
        except Exception as e:
            print(f"Erro cache warmup: {e}")
    threading.Thread(target=_warm, daemon=True).start()

# Aquece cache ao iniciar o servidor
_aquecer_cache()

@app.route('/')
def home():
    return jsonify({"status": "online", "mensagem": "API Átomo funcionando!"})

@app.route('/api/filtros')
def filtros():
    key    = 'filtros'
    cached = cache_get(key)
    if cached: return jsonify(cached)

    # Uma conexão, queries executadas sequencialmente
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
    cursor.close(); conn.close()
    cache_set(key, resultado)
    return jsonify(resultado)


@app.route('/api/dashboard')
def dashboard():
    """Retorna KPIs + mensal + unidade + vendedores + marcas em UMA chamada."""
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
        SELECT ano, mes,
            ROUND(CAST(SUM(CASE WHEN tipo_operacao='Venda' THEN valor_nf ELSE 0 END) AS NUMERIC),2) AS faturamento,
            ROUND(CAST(SUM(CASE WHEN tipo_operacao='Devolucao' THEN valor_nf ELSE 0 END) AS NUMERIC),2) AS devolucoes
        FROM faturamento {where} {and_or} mes > 0
        GROUP BY ano, mes ORDER BY ano, mes
    """, params)

    unidade = run(f"""
        SELECT unidade,
            ROUND(CAST(SUM(CASE WHEN tipo_operacao='Venda' THEN valor_nf ELSE 0 END) AS NUMERIC),2) AS faturamento,
            ROUND(CAST(SUM(CASE WHEN tipo_operacao='Devolucao' THEN valor_nf ELSE 0 END) AS NUMERIC),2) AS devolucoes,
            COUNT(DISTINCT cliente) AS clientes
        FROM faturamento {where} {and_or} unidade IS NOT NULL
        GROUP BY unidade ORDER BY faturamento DESC
    """, params)

    vendedores = run(f"""
        SELECT vendedor,
            ROUND(CAST(SUM(valor_nf) AS NUMERIC),2) AS faturamento,
            COUNT(DISTINCT cliente) AS clientes
        FROM faturamento {where} {and_or} tipo_operacao='Venda'
        GROUP BY vendedor ORDER BY faturamento DESC LIMIT 10
    """, params)

    marcas = run(f"""
        SELECT marca,
            ROUND(CAST(SUM(valor_nf) AS NUMERIC),2) AS faturamento,
            COUNT(DISTINCT cliente) AS clientes
        FROM faturamento {where} {and_or} tipo_operacao='Venda' AND marca IS NOT NULL
        GROUP BY marca ORDER BY faturamento DESC LIMIT 15
    """, params)

    cursor.close(); conn.close()

    resultado = {
        'kpis':       kpis[0] if kpis else {},
        'mensal':     mensal,
        'unidade':    unidade,
        'vendedores': vendedores,
        'marcas':     marcas,
    }
    cache_set(key, resultado)
    return jsonify(resultado)

@app.route('/api/kpis')
def kpis():
    key    = cache_key('kpis', dict(request.args))
    cached = cache_get(key)
    if cached: return jsonify(cached)

    where, params = montar_filtros(request.args)
    resultado = consultar(f"""
        SELECT
            ROUND(CAST(SUM(CASE WHEN tipo_operacao = 'Venda' THEN valor_nf ELSE 0 END) AS NUMERIC), 2) AS faturamento,
            ROUND(CAST(SUM(CASE WHEN tipo_operacao = 'Devolucao' THEN valor_nf ELSE 0 END) AS NUMERIC), 2) AS devolucoes,
            ROUND(CAST(SUM(CASE WHEN tipo_operacao = 'Bonificacao' THEN valor_nf ELSE 0 END) AS NUMERIC), 2) AS bonificacoes,
            ROUND(CAST(SUM(CASE WHEN tipo_operacao = 'Venda' THEN valor_nf ELSE 0 END) /
                NULLIF(COUNT(CASE WHEN tipo_operacao = 'Venda' THEN 1 END), 0) AS NUMERIC), 2) AS ticket_medio,
            COUNT(DISTINCT cliente) AS total_clientes,
            COUNT(CASE WHEN tipo_operacao = 'Venda' THEN 1 END) AS qtd_vendas
        FROM faturamento {where}
    """, params)

    r = resultado[0] if resultado else {}
    cache_set(key, r)
    return jsonify(r)

@app.route('/api/faturamento-mensal')
def faturamento_mensal():
    key    = cache_key('faturamento-mensal', dict(request.args))
    cached = cache_get(key)
    if cached: return jsonify(cached)

    where, params = montar_filtros(request.args)
    resultado = consultar(f"""
        SELECT ano, mes,
            ROUND(CAST(SUM(CASE WHEN tipo_operacao = 'Venda' THEN valor_nf ELSE 0 END) AS NUMERIC), 2) AS faturamento,
            ROUND(CAST(SUM(CASE WHEN tipo_operacao = 'Devolucao' THEN valor_nf ELSE 0 END) AS NUMERIC), 2) AS devolucoes,
            ROUND(CAST(SUM(CASE WHEN tipo_operacao = 'Bonificacao' THEN valor_nf ELSE 0 END) AS NUMERIC), 2) AS bonificacoes
        FROM faturamento {where}
        {'AND' if where else 'WHERE'} mes > 0
        GROUP BY ano, mes ORDER BY ano, mes
    """, params)

    cache_set(key, resultado)
    return jsonify(resultado)

@app.route('/api/top-vendedores')
def top_vendedores():
    key    = cache_key('top-vendedores', dict(request.args))
    cached = cache_get(key)
    if cached: return jsonify(cached)

    where, params = montar_filtros(request.args)
    limite   = int(request.args.get('limite', 10))
    and_or   = 'AND' if where else 'WHERE'
    resultado = consultar(f"""
        SELECT vendedor,
            ROUND(CAST(SUM(valor_nf) AS NUMERIC), 2) AS faturamento,
            COUNT(DISTINCT cliente) AS clientes,
            COUNT(DISTINCT unidade) AS unidades,
            COUNT(*) AS qtd_vendas
        FROM faturamento {where} {and_or} tipo_operacao = 'Venda'
        GROUP BY vendedor ORDER BY faturamento DESC LIMIT %s
    """, params + [limite])

    cache_set(key, resultado)
    return jsonify(resultado)

@app.route('/api/faturamento-por-marca')
def faturamento_por_marca():
    key    = cache_key('faturamento-por-marca', dict(request.args))
    cached = cache_get(key)
    if cached: return jsonify(cached)

    where, params = montar_filtros(request.args)
    limite   = int(request.args.get('limite', 15))
    and_or   = 'AND' if where else 'WHERE'
    resultado = consultar(f"""
        SELECT marca,
            ROUND(CAST(SUM(valor_nf) AS NUMERIC), 2) AS faturamento,
            COUNT(DISTINCT cliente) AS clientes
        FROM faturamento {where} {and_or} tipo_operacao = 'Venda'
        GROUP BY marca ORDER BY faturamento DESC LIMIT %s
    """, params + [limite])

    cache_set(key,