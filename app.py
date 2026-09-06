from flask import Flask, jsonify, request, send_file, g
from flask_cors import CORS
from flask import has_request_context
import psycopg2
import psycopg2.extras
import psycopg2.pool
import psycopg2.extensions
import os
import re
import time
import json
import io
import datetime
import traceback as tb

app = Flask(__name__)
CORS(app)


# ------------------------------------------------------------
# CACHE HTTP
# ------------------------------------------------------------
@app.teardown_request
def _devolver_conexoes(exc):
    for c in getattr(g, '_conns', []):
        try:
            c.close()
        except Exception:
            pass


@app.after_request
def _cache_headers(resp):
    try:
        _sem_cache = ('/api/shelflife/semanas', '/api/shelflife/listar')
        if request.method == 'GET' and request.path in _sem_cache:
            resp.headers['Cache-Control'] = 'no-store, max-age=0'
        elif request.method == 'GET' and request.path.startswith('/api/') and resp.status_code == 200:
            resp.headers.setdefault(
                'Cache-Control',
                'public, max-age=300, stale-while-revalidate=86400'
            )
    except Exception:
        pass
    return resp


# ============================================================
# CACHE EM MEMÓRIA
# ============================================================
_cache = {}
CACHE_TTL = 28800  # 8 horas

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
_POOL = None

def _init_pool():
    global _POOL
    if _POOL is None:
        _POOL = psycopg2.pool.ThreadedConnectionPool(
            1, int(os.environ.get('DB_POOL_MAX', 10)),
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
    return _POOL


class _PooledConn:
    def __init__(self, conn):
        self._conn = conn
        self._returned = False

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        if self._returned:
            return
        self._returned = True
        try:
            if self._conn.closed:
                _init_pool().putconn(self._conn, close=True)
                return
            if self._conn.get_transaction_status() != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
                self._conn.rollback()
            _init_pool().putconn(self._conn)
        except Exception:
            try:
                _init_pool().putconn(self._conn, close=True)
            except Exception:
                pass

    def __enter__(self):
        return self._conn.__enter__()

    def __exit__(self, *a):
        return self._conn.__exit__(*a)


def get_conn():
    last_err = None
    for attempt in range(3):
        try:
            pool = _init_pool()
            conn = pool.getconn()
            try:
                cur = conn.cursor()
                cur.execute('SELECT 1')
                cur.close()
            except Exception:
                try:
                    pool.putconn(conn, close=True)
                except Exception:
                    pass
                conn = pool.getconn()
            wrapped = _PooledConn(conn)
            try:
                if has_request_context():
                    if not hasattr(g, '_conns'):
                        g._conns = []
                    g._conns.append(wrapped)
            except Exception:
                pass
            return wrapped
        except Exception as e:
            last_err = e
            global _POOL
            _POOL = None
            time.sleep(0.3 * (attempt + 1))
    raise last_err


def _serializar_row(row):
    out = {}
    for k, v in row.items():
        if isinstance(v, datetime.date):
            try:
                out[k] = v.isoformat()
            except Exception:
                out[k] = None
        else:
            out[k] = v
    return out


def consultar(sql, params=()):
    conn = get_conn()
    try:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute(sql, params)
        try:
            rows = [_serializar_row(dict(r)) for r in cursor.fetchall()]
        except Exception:
            cursor.execute(sql, params)
            rows = []
            while True:
                try:
                    row = cursor.fetchone()
                except Exception:
                    continue
                if row is None:
                    break
                try:
                    rows.append(_serializar_row(dict(row)))
                except Exception:
                    continue
        cursor.close()
        return rows
    finally:
        conn.close()


# ============================================================
# FILTROS
# ============================================================
def montar_filtros(args):
    condicoes = []
    params = []

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
        nomes_norm = [' '.join(str(v).strip().upper().split()) for v in vendedores]
        ph_norm = ','.join(['%s'] * len(nomes_norm))
        condicoes.append(
            "("
            "  UPPER(BTRIM(vendedor)) IN (" + ph_norm + ")"
            "  OR (cod_vendedor IS NOT NULL AND cod_vendedor::TEXT <> '' AND cod_vendedor::TEXT IN ("
            "        SELECT DISTINCT f2.cod_vendedor::TEXT FROM faturamento f2"
            "         WHERE UPPER(BTRIM(f2.vendedor)) IN (" + ph_norm + ")"
            "           AND f2.cod_vendedor IS NOT NULL AND f2.cod_vendedor::TEXT <> ''"
            "        UNION"
            "        SELECT DISTINCT v2.cod_vendedor::TEXT FROM vendedores v2"
            "         WHERE UPPER(BTRIM(v2.nome)) IN (" + ph_norm + ")"
            "           AND v2.cod_vendedor IS NOT NULL AND v2.cod_vendedor::TEXT <> ''"
            "     ))"
            ")"
        )
        params.extend(nomes_norm)
        params.extend(nomes_norm)
        params.extend(nomes_norm)

    where = ("WHERE " + " AND ".join(condicoes)) if condicoes else ""
    return where, params


def cache_key(rota, args):
    return rota + '?' + '&'.join(f'{k}={v}' for k, v in sorted(args.items()))


# ============================================================
# ROTAS PRINCIPAIS
# ============================================================

@app.route('/')
def home():
    return jsonify({"status": "online", "mensagem": "API Átomo funcionando!"})


@app.route('/ping')
def ping():
    return jsonify({"status": "pong", "uptime": "ok"})


@app.route('/api/cache/clear', methods=['GET', 'POST'])
def limpar_cache():
    cache_clear()
    return jsonify({"status": "cache limpo!"})


@app.route('/api/filtros')
def filtros():
    key = 'filtros'
    cached = cache_get(key)
    if cached:
        return jsonify(cached)

    # Se não tiver conexão com banco, retorna dados mock
    try:
        conn = get_conn()
        cursor = conn.cursor()

        def q(sql):
            cursor.execute(sql)
            return [r[0] for r in cursor.fetchall()]

        resultado = {
            'anos': q("SELECT DISTINCT ano FROM faturamento WHERE ano IS NOT NULL AND ano > 0 ORDER BY ano DESC"),
            'meses': q("SELECT DISTINCT mes FROM faturamento WHERE mes IS NOT NULL AND mes > 0 ORDER BY mes"),
            'unidades': q("SELECT DISTINCT unidade FROM faturamento WHERE unidade IS NOT NULL ORDER BY unidade"),
            'ufs': q("SELECT DISTINCT uf FROM faturamento WHERE uf IS NOT NULL AND uf != '' ORDER BY uf"),
            'marcas': q("SELECT DISTINCT marca FROM faturamento WHERE marca IS NOT NULL ORDER BY marca"),
            'tipos': q("SELECT DISTINCT tipo_operacao FROM faturamento WHERE tipo_operacao IS NOT NULL ORDER BY tipo_operacao"),
            'vendedores': q("SELECT DISTINCT vendedor FROM faturamento WHERE vendedor IS NOT NULL ORDER BY vendedor"),
        }
        cursor.close()
        conn.close()
        cache_set(key, resultado)
        return jsonify(resultado)
    except Exception as e:
        # Fallback: retorna dados mock se o banco não estiver disponível
        print(f"Erro ao conectar ao banco: {e}")
        return jsonify({
            'anos': [2024, 2025, 2026],
            'meses': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
            'unidades': ['PR', 'RS', 'SC', 'SP'],
            'ufs': ['PR', 'RS', 'SC', 'SP', 'MG', 'RJ'],
            'marcas': ['Marca A', 'Marca B', 'Marca C'],
            'tipos': ['Venda', 'Devolucao'],
            'vendedores': ['Vendedor 1', 'Vendedor 2', 'Vendedor 3']
        })


@app.route('/api/dashboard')
def dashboard():
    key = cache_key('dashboard', dict(request.args))
    cached = cache_get(key)
    if cached:
        return jsonify(cached)

    where, params = montar_filtros(request.args)
    and_or = 'AND' if where else 'WHERE'

    try:
        conn = get_conn()
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

        cursor.close()
        conn.close()

        resultado = {
            'kpis': kpis[0] if kpis else {},
            'mensal': mensal,
            'unidade': unidade,
            'vendedores': vendedores,
            'marcas': marcas,
        }
        cache_set(key, resultado)
        return jsonify(resultado)
    except Exception as e:
        print(f"Erro no dashboard: {e}")
        return jsonify({
            'kpis': {'faturamento': 0, 'devolucoes': 0, 'total_clientes': 0, 'ticket_medio': 0, 'qtd_vendas': 0},
            'mensal': [],
            'unidade': [],
            'vendedores': [],
            'marcas': []
        })


@app.route('/api/kpis')
def kpis():
    key = cache_key('kpis', dict(request.args))
    cached = cache_get(key)
    if cached:
        return jsonify(cached)

    where, params = montar_filtros(request.args)
    
    try:
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
    except Exception as e:
        print(f"Erro no kpis: {e}")
        return jsonify({
            'faturamento': 0,
            'devolucoes': 0,
            'bonificacoes': 0,
            'ticket_medio': 0,
            'total_clientes': 0,
            'qtd_vendas': 0
        })


@app.route('/api/faturamento-mensal')
def faturamento_mensal():
    key = cache_key('faturamento-mensal', dict(request.args))
    cached = cache_get(key)
    if cached:
        return jsonify(cached)

    where, params = montar_filtros(request.args)
    
    try:
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
    except Exception as e:
        print(f"Erro no faturamento-mensal: {e}")
        return jsonify([])


@app.route('/api/top-vendedores')
def top_vendedores():
    key = cache_key('top-vendedores', dict(request.args))
    cached = cache_get(key)
    if cached:
        return jsonify(cached)

    where, params = montar_filtros(request.args)
    limite = int(request.args.get('limite', 10))
    and_or = 'AND' if where else 'WHERE'
    
    try:
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
    except Exception as e:
        print(f"Erro no top-vendedores: {e}")
        return jsonify([])


@app.route('/api/faturamento-por-marca')
def faturamento_por_marca():
    key = cache_key('faturamento-por-marca', dict(request.args))
    cached = cache_get(key)
    if cached:
        return jsonify(cached)

    where, params = montar_filtros(request.args)
    limite = int(request.args.get('limite', 15))
    and_or = 'AND' if where else 'WHERE'
    
    try:
        resultado = consultar(f"""
            SELECT marca,
                ROUND(CAST(SUM(valor_nf) AS NUMERIC), 2) AS faturamento,
                COUNT(DISTINCT cliente) AS clientes
            FROM faturamento {where} {and_or} tipo_operacao = 'Venda'
            GROUP BY marca ORDER BY faturamento DESC LIMIT %s
        """, params + [limite])

        cache_set(key, resultado)
        return jsonify(resultado)
    except Exception as e:
        print(f"Erro no faturamento-por-marca: {e}")
        return jsonify([])


@app.route('/api/top-produtos')
def top_produtos():
    key = cache_key('top-produtos', dict(request.args))
    cached = cache_get(key)
    if cached:
        return jsonify(cached)

    where, params = montar_filtros(request.args)
    limite = int(request.args.get('limite', 10))
    and_or = 'AND' if where else 'WHERE'
    
    try:
        resultado = consultar(f"""
            SELECT produto, marca,
                ROUND(CAST(SUM(valor_nf) AS NUMERIC), 2) AS faturamento,
                ROUND(CAST(SUM(quantidade) AS NUMERIC), 0) AS quantidade
            FROM faturamento {where} {and_or} tipo_operacao = 'Venda'
            GROUP BY produto, marca ORDER BY faturamento DESC LIMIT %s
        """, params + [limite])

        cache_set(key, resultado)
        return jsonify(resultado)
    except Exception as e:
        print(f"Erro no top-produtos: {e}")
        return jsonify([])


@app.route('/api/top-clientes')
def top_clientes():
    key = cache_key('top-clientes', dict(request.args))
    cached = cache_get(key)
    if cached:
        return jsonify(cached)

    where, params = montar_filtros(request.args)
    limite = int(request.args.get('limite', 10))
    and_or = 'AND' if where else 'WHERE'
    
    try:
        resultado = consultar(f"""
            SELECT cliente,
                ROUND(CAST(SUM(valor_nf) AS NUMERIC), 2) AS faturamento,
                COUNT(*) AS qtd_vendas
            FROM faturamento {where} {and_or} tipo_operacao = 'Venda'
            GROUP BY cliente ORDER BY faturamento DESC LIMIT %s
        """, params + [limite])

        cache_set(key, resultado)
        return jsonify(resultado)
    except Exception as e:
        print(f"Erro no top-clientes: {e}")
        return jsonify([])


@app.route('/api/faturamento-por-regiao')
def faturamento_por_regiao():
    key = cache_key('faturamento-por-regiao', dict(request.args))
    cached = cache_get(key)
    if cached:
        return jsonify(cached)

    where, params = montar_filtros(request.args)
    and_or = 'AND' if where else 'WHERE'
    
    try:
        resultado = consultar(f"""
            SELECT regiao,
                ROUND(CAST(SUM(valor_nf) AS NUMERIC), 2) AS faturamento,
                COUNT(DISTINCT cliente) AS clientes
            FROM faturamento {where} {and_or} tipo_operacao = 'Venda'
            AND regiao IS NOT NULL AND regiao != ''
            GROUP BY regiao ORDER BY faturamento DESC
        """, params)

        cache_set(key, resultado)
        return jsonify(resultado)
    except Exception as e:
        print(f"Erro no faturamento-por-regiao: {e}")
        return jsonify([])


@app.route('/api/faturamento-por-unidade')
def faturamento_por_unidade():
    key = cache_key('faturamento-por-unidade', dict(request.args))
    cached = cache_get(key)
    if cached:
        return jsonify(cached)

    where, params = montar_filtros(request.args)
    and_or = 'AND' if where else 'WHERE'
    
    try:
        resultado = consultar(f"""
            SELECT unidade,
                ROUND(CAST(SUM(CASE WHEN tipo_operacao = 'Venda' THEN valor_nf ELSE 0 END) AS NUMERIC), 2) AS faturamento,
                ROUND(CAST(SUM(CASE WHEN tipo_operacao = 'Devolucao' THEN valor_nf ELSE 0 END) AS NUMERIC), 2) AS devolucoes,
                ROUND(CAST(SUM(CASE WHEN tipo_operacao = 'Bonificacao' THEN valor_nf ELSE 0 END) AS NUMERIC), 2) AS bonificacoes,
                COUNT(DISTINCT cliente) AS clientes
            FROM faturamento {where} {and_or} unidade IS NOT NULL
            GROUP BY unidade ORDER BY faturamento DESC
        """, params)

        cache_set(key, resultado)
        return jsonify(resultado)
    except Exception as e:
        print(f"Erro no faturamento-por-unidade: {e}")
        return jsonify([])


@app.route('/api/faturamento-por-uf')
def faturamento_por_uf():
    key = cache_key('faturamento-por-uf', dict(request.args))
    cached = cache_get(key)
    if cached:
        return jsonify(cached)

    where, params = montar_filtros(request.args)
    and_or = 'AND' if where else 'WHERE'
    
    try:
        resultado = consultar(f"""
            SELECT uf,
                ROUND(CAST(SUM(valor_nf) AS NUMERIC), 2) AS faturamento,
                COUNT(DISTINCT cliente) AS clientes
            FROM faturamento {where} {and_or} tipo_operacao = 'Venda'
            AND uf IS NOT NULL AND uf != ''
            GROUP BY uf ORDER BY faturamento DESC
        """, params)

        cache_set(key, resultado)
        return jsonify(resultado)
    except Exception as e:
        print(f"Erro no faturamento-por-uf: {e}")
        return jsonify([])


@app.route('/api/faturamento-por-cidade')
def faturamento_por_cidade():
    key = cache_key('faturamento-por-cidade', dict(request.args))
    cached = cache_get(key)
    if cached:
        return jsonify(cached)

    where, params = montar_filtros(request.args)
    limite = int(request.args.get('limite', 15))
    and_or = 'AND' if where else 'WHERE'
    
    try:
        resultado = consultar(f"""
            SELECT cidade, uf,
                ROUND(CAST(SUM(valor_nf) AS NUMERIC), 2) AS faturamento,
                COUNT(DISTINCT cliente) AS clientes
            FROM faturamento {where} {and_or} tipo_operacao = 'Venda'
            AND cidade IS NOT NULL AND cidade != ''
            GROUP BY cidade, uf ORDER BY faturamento DESC LIMIT %s
        """, params + [limite])

        cache_set(key, resultado)
        return jsonify(resultado)
    except Exception as e:
        print(f"Erro no faturamento-por-cidade: {e}")
        return jsonify([])


@app.route('/api/todos-produtos')
def todos_produtos():
    key = 'todos_produtos'
    cached = cache_get(key)
    if cached:
        return jsonify(cached)

    try:
        resultado = consultar("""
            SELECT DISTINCT produto, cod_produto, marca
            FROM faturamento
            WHERE produto IS NOT NULL AND produto != ''
            ORDER BY produto
        """)
        cache_set(key, resultado)
        return jsonify(resultado)
    except Exception as e:
        print(f"Erro no todos-produtos: {e}")
        return jsonify([])


@app.route('/api/resumo-carteira')
def resumo_carteira():
    key = cache_key('resumo-carteira', dict(request.args))
    cached = cache_get(key)
    if cached:
        return jsonify(cached)

    vendedor = request.args.get('vendedor', '')
    where, params = montar_filtros(request.args)
    and_or = 'AND' if where else 'WHERE'

    try:
        margem = consultar(f"""
            SELECT ROUND(CAST(AVG(margem) AS NUMERIC), 2) AS margem_media
            FROM faturamento {where}
            {and_or} tipo_operacao = 'Venda'
            AND margem IS NOT NULL AND margem != 0
        """, params)
        margem_media = margem[0]['margem_media'] if margem else 0

        carteira = consultar("""
            SELECT
                COUNT(*) AS total_codigos,
                COUNT(DISTINCT NULLIF(TRIM(cnpj_cpf), '')) AS total_cnpjs
            FROM carteira
        """)

        total_codigos = carteira[0]['total_codigos'] if carteira else 0
        total_cnpjs = carteira[0]['total_cnpjs'] if carteira else 0
        
        resultado = {
            'total_carteira': total_cnpjs,
            'total_codigos': total_codigos,
            'margem_media': float(margem_media) if margem_media else 0,
        }
        cache_set(key, resultado)
        return jsonify(resultado)
    except Exception as e:
        print(f"Erro no resumo-carteira: {e}")
        return jsonify({'total_carteira': 0, 'total_codigos': 0, 'margem_media': 0})


@app.route('/api/clientes-em-risco')
def clientes_em_risco():
    try:
        dias = int(request.args.get('dias', 60))
        limit = int(request.args.get('limite', 200))

        resultado = consultar("""
            SELECT
                f.cod_cliente,
                f.cliente,
                f.vendedor,
                MAX(f.data_movimento)::TEXT AS ultima_compra,
                (CURRENT_DATE - MAX(f.data_movimento::DATE))::INT AS dias_sem_compra,
                ROUND(CAST(SUM(CASE WHEN f.tipo_operacao='Venda' THEN f.valor_nf ELSE 0 END) AS NUMERIC),2) AS fat_total,
                COUNT(DISTINCT f.data_movimento) AS num_pedidos
            FROM faturamento f
            WHERE f.tipo_operacao='Venda' AND f.cliente IS NOT NULL
            GROUP BY f.cod_cliente, f.cliente, f.vendedor
            HAVING (CURRENT_DATE - MAX(f.data_movimento::DATE))::INT >= %s
            ORDER BY dias_sem_compra DESC
            LIMIT %s
        """, [dias, limit])

        return jsonify({'clientes': resultado, 'total': len(resultado), 'dias_corte': dias})
    except Exception as e:
        print(f"Erro no clientes-em-risco: {e}")
        return jsonify({'clientes': [], 'total': 0, 'dias_corte': dias})


@app.route('/api/pivot-clientes')
def pivot_clientes():
    try:
        vendedores = request.args.getlist('vendedor')
        produtos = request.args.getlist('produtos')
        periodos = request.args.getlist('periodo')
        unidades = request.args.getlist('unidade')

        # Monta query
        where = []
        params = []

        if vendedores:
            placeholders = ','.join(['%s'] * len(vendedores))
            where.append(f"vendedor IN ({placeholders})")
            params.extend(vendedores)

        if produtos:
            placeholders = ','.join(['%s'] * len(produtos))
            where.append(f"produto IN ({placeholders})")
            params.extend(produtos)

        if unidades:
            placeholders = ','.join(['%s'] * len(unidades))
            where.append(f"unidade IN ({placeholders})")
            params.extend(unidades)

        if periodos:
            conds = []
            for per in periodos:
                try:
                    ano_p, mes_p = per.split('-')
                    conds.append('(ano = %s AND mes = %s)')
                    params.extend([int(ano_p), int(mes_p)])
                except:
                    pass
            if conds:
                where.append(f"({' OR '.join(conds)})")

        where_str = 'WHERE ' + ' AND '.join(where) if where else ''

        sql = f"""
            SELECT
                cod_cliente,
                cliente,
                vendedor,
                unidade,
                ano,
                mes,
                ROUND(CAST(SUM(CASE WHEN tipo_operacao='Venda' THEN valor_nf ELSE 0 END) AS NUMERIC),2) AS faturamento,
                ROUND(CAST(SUM(CASE WHEN tipo_operacao='Devolucao' THEN ABS(valor_nf) ELSE 0 END) AS NUMERIC),2) AS devolucoes
            FROM faturamento
            {where_str}
            GROUP BY cod_cliente, cliente, vendedor, unidade, ano, mes
            ORDER BY cliente, ano, mes
        """

        resultado = consultar(sql, params)
        return jsonify(resultado)
    except Exception as e:
        print(f"Erro no pivot-clientes: {e}")
        return jsonify([])


# ============================================================
# SHELF LIFE - ROTAS BÁSICAS
# ============================================================

@app.route('/api/shelflife/verificar-acesso', methods=['POST'])
def shelflife_verificar_acesso():
    data = request.get_json(force=True)
    email = str(data.get('email', '')).strip().lower()
    # Lista de e-mails autorizados
    emails_autorizados = [
        'comercial2@reforpan.com.br',
        'comercial3@esdel.com.br',
        'comercial1@esdel.com'
    ]
    autorizado = email in [e.lower() for e in emails_autorizados]
    return jsonify({'autorizado': autorizado, 'email': email})


@app.route('/api/shelflife/semanas')
def shelflife_semanas():
    try:
        resultado = consultar("""
            SELECT DISTINCT semana, unidade, COUNT(*) as total
            FROM shelflife GROUP BY semana, unidade ORDER BY semana DESC
        """)
        return jsonify(resultado)
    except Exception as e:
        print(f"Erro no shelflife/semanas: {e}")
        return jsonify([])


@app.route('/api/shelflife/listar')
def shelflife_listar():
    try:
        semana = request.args.get('semana')
        unidade = request.args.get('unidade')
        where = []
        params = []

        if semana:
            where.append('semana = %s')
            params.append(semana)
        else:
            where.append('semana = (SELECT MAX(semana) FROM shelflife)')

        if unidade:
            where.append('unidade = %s')
            params.append(unidade)

        where_str = 'WHERE ' + ' AND '.join(where) if where else ''
        resultado = consultar('SELECT * FROM shelflife ' + where_str + ' ORDER BY validade ASC NULLS LAST', params)
        return jsonify(resultado)
    except Exception as e:
        print(f"Erro no shelflife/listar: {e}")
        return jsonify([])


# ============================================================
# VALTER - ASSISTENTE IA
# ============================================================

@app.route('/api/valter/chat', methods=['POST'])
def valter_chat():
    try:
        data = request.get_json(force=True)
        mensagem = data.get('mensagem', '')
        
        # Resposta simples para teste
        return jsonify({
            'resposta': f"Olá! Recebi sua pergunta: '{mensagem}'. O sistema Átomo está funcionando!",
            'content': [{'type': 'text', 'text': f"Olá! Recebi sua pergunta: '{mensagem}'. O sistema Átomo está funcionando!"}]
        })
    except Exception as e:
        return jsonify({'erro': str(e)}), 500


@app.route('/api/valter/alertas')
def valter_alertas():
    try:
        # Retorna alertas mock para teste
        return jsonify({
            'alertas': [
                {'icone': '⚠️', 'texto': 'Nenhum alerta no momento', 'tipo': 'info'}
            ]
        })
    except Exception as e:
        return jsonify({'alertas': [], 'erro': str(e)})


# ============================================================
# EXPORTAÇÃO
# ============================================================

@app.route('/api/exportar', methods=['GET'])
def exportar_dados():
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Dados'
        
        ws.append(['KPI', 'Valor'])
        ws.append(['Status', 'API funcionando!'])
        
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        filename = f'Atomo_Export_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
        return send_file(
            buf,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================================
# INICIALIZAÇÃO
# ============================================================

if __name__ == '__main__':
    # Tenta conectar ao banco para aquecer o cache
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
        conn.close()
        print("✅ Banco conectado com sucesso!")
    except Exception as e:
        print(f"⚠️ Erro ao conectar ao banco: {e}")
        print("⚠️ O sistema funcionará com dados mock para teste")

    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=False)
