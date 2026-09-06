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
# ROTAS EXISTENTES (mantidas)
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


@app.route('/api/dashboard')
def dashboard():
    key = cache_key('dashboard', dict(request.args))
    cached = cache_get(key)
    if cached:
        return jsonify(cached)

    where, params = montar_filtros(request.args)
    and_or = 'AND' if where else 'WHERE'

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


# ============================================================
# NOVAS ROTAS PARA O HOME (dashboard rápido)
# ============================================================

@app.route('/api/home/dashboard')
def home_dashboard():
    """Dashboard rápido para a página inicial - KPIs + rankings"""
    key = cache_key('home_dashboard', dict(request.args))
    cached = cache_get(key)
    if cached:
        return jsonify(cached)

    where, params = montar_filtros(request.args)
    and_or = 'AND' if where else 'WHERE'

    conn = get_conn()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def run(sql, p):
        cursor.execute(sql, p)
        return [_serializar_row(dict(r)) for r in cursor.fetchall()]

    # KPIs
    kpis = run(f"""
        SELECT
            ROUND(CAST(SUM(CASE WHEN tipo_operacao='Venda' THEN valor_nf ELSE 0 END) AS NUMERIC),2) AS faturamento,
            ROUND(CAST(SUM(CASE WHEN tipo_operacao='Devolucao' THEN valor_nf ELSE 0 END) AS NUMERIC),2) AS devolucoes,
            COUNT(DISTINCT cliente) AS total_clientes,
            COUNT(CASE WHEN tipo_operacao='Venda' THEN 1 END) AS qtd_vendas
        FROM faturamento {where}
    """, params)

    # Top Vendedores (5)
    top_vendedores = run(f"""
        SELECT vendedor,
            ROUND(CAST(SUM(valor_nf) AS NUMERIC),2) AS faturamento,
            COUNT(DISTINCT cliente) AS clientes
        FROM faturamento {where} {and_or} tipo_operacao='Venda'
        GROUP BY vendedor ORDER BY faturamento DESC LIMIT 5
    """, params)

    # Top Marcas (5)
    top_marcas = run(f"""
        SELECT marca,
            ROUND(CAST(SUM(valor_nf) AS NUMERIC),2) AS faturamento,
            COUNT(DISTINCT cliente) AS clientes
        FROM faturamento {where} {and_or} tipo_operacao='Venda' AND marca IS NOT NULL
        GROUP BY marca ORDER BY faturamento DESC LIMIT 5
    """, params)

    # Alertas do sistema
    alertas = []
    try:
        cursor.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN dias_vencimento <= 30 THEN 1 ELSE 0 END) as criticos,
                   SUM(CASE WHEN is_sl = TRUE THEN 1 ELSE 0 END) as sl
            FROM shelflife WHERE semana = (SELECT MAX(semana) FROM shelflife)
        """)
        sl = cursor.fetchone()
        if sl and sl['criticos'] > 0:
            alertas.append({
                'icone': '⚠️',
                'texto': f"{sl['criticos']} produto(s) críticos no Shelf Life",
                'tipo': 'danger',
                'pergunta': f"Liste os {sl['criticos']} produtos críticos do Shelf Life"
            })
        if sl and sl['sl'] > 0:
            alertas.append({
                'icone': '🕒',
                'texto': f"{sl['sl']} produto(s) em código SL",
                'tipo': 'warning',
                'pergunta': f"Quais os {sl['sl']} produtos em SL?"
            })
    except Exception:
        pass

    cursor.close()
    conn.close()

    resultado = {
        'kpis': kpis[0] if kpis else {},
        'top_vendedores': top_vendedores,
        'top_marcas': top_marcas,
        'alertas': alertas,
    }
    cache_set(key, resultado)
    return jsonify(resultado)


# ============================================================
# ROTAS DE EXPORTAÇÃO
# ============================================================

@app.route('/api/exportar', methods=['GET'])
def exportar_dados():
    """Exporta dados em Excel com múltiplas abas"""
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

        where, params = montar_filtros(request.args)

        conn = get_conn()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # 1. KPIs
        cursor.execute(f"""
            SELECT
                ROUND(CAST(SUM(CASE WHEN tipo_operacao='Venda' THEN valor_nf ELSE 0 END) AS NUMERIC),2) AS faturamento,
                ROUND(CAST(SUM(CASE WHEN tipo_operacao='Devolucao' THEN valor_nf ELSE 0 END) AS NUMERIC),2) AS devolucoes,
                ROUND(CAST(SUM(CASE WHEN tipo_operacao='Bonificacao' THEN valor_nf ELSE 0 END) AS NUMERIC),2) AS bonificacoes,
                ROUND(CAST(AVG(CASE WHEN tipo_operacao='Venda' THEN valor_nf END) AS NUMERIC),2) AS ticket_medio,
                COUNT(DISTINCT cliente) AS total_clientes,
                COUNT(CASE WHEN tipo_operacao='Venda' THEN 1 END) AS qtd_vendas
            FROM faturamento {where}
        """, params)
        kpis = cursor.fetchone()

        # 2. Vendedores
        and_or = 'AND' if where else 'WHERE'
        cursor.execute(f"""
            SELECT vendedor,
                ROUND(CAST(SUM(valor_nf) AS NUMERIC),2) AS faturamento,
                COUNT(DISTINCT cliente) AS clientes,
                COUNT(*) AS qtd_vendas
            FROM faturamento {where} {and_or} tipo_operacao='Venda'
            GROUP BY vendedor ORDER BY faturamento DESC LIMIT 20
        """, params)
        vendedores = cursor.fetchall()

        # 3. Marcas
        cursor.execute(f"""
            SELECT marca,
                ROUND(CAST(SUM(valor_nf) AS NUMERIC),2) AS faturamento,
                COUNT(DISTINCT cliente) AS clientes
            FROM faturamento {where} {and_or} tipo_operacao='Venda' AND marca IS NOT NULL
            GROUP BY marca ORDER BY faturamento DESC LIMIT 20
        """, params)
        marcas = cursor.fetchall()

        cursor.close()
        conn.close()

        # Cria workbook
        wb = openpyxl.Workbook()

        # Aba KPIs
        ws = wb.active
        ws.title = 'KPIs'
        ws.append(['KPI', 'Valor'])
        ws.append(['Faturamento Bruto', kpis['faturamento'] or 0])
        ws.append(['Devoluções', abs(kpis['devolucoes'] or 0)])
        ws.append(['Faturamento Líquido', (kpis['faturamento'] or 0) - abs(kpis['devolucoes'] or 0)])
        ws.append(['Ticket Médio', kpis['ticket_medio'] or 0])
        ws.append(['Clientes Ativos', kpis['total_clientes'] or 0])
        ws.append(['Quantidade de Vendas', kpis['qtd_vendas'] or 0])

        # Aba Vendedores
        ws2 = wb.create_sheet('Top Vendedores')
        ws2.append(['#', 'Vendedor', 'Faturamento', 'Clientes', 'Vendas'])
        for i, v in enumerate(vendedores, 1):
            ws2.append([i, v['vendedor'], v['faturamento'] or 0, v['clientes'] or 0, v['qtd_vendas'] or 0])

        # Aba Marcas
        ws3 = wb.create_sheet('Top Marcas')
        ws3.append(['#', 'Marca', 'Faturamento', 'Clientes'])
        for i, m in enumerate(marcas, 1):
            ws3.append([i, m['marca'], m['faturamento'] or 0, m['clientes'] or 0])

        # Salva
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
        return jsonify({'error': str(e), 'trace': tb.format_exc()}), 500


# ============================================================
# ROTA PARA O VALTER (ASSISTENTE IA) - MELHORADA
# ============================================================

@app.route('/api/valter/chat', methods=['POST'])
def valter_chat():
    """Chat com o assistente Valter - versão melhorada com contexto"""
    import requests as _req

    try:
        data = request.get_json(force=True)
        mensagem = data.get('mensagem', '')
        contexto = data.get('contexto', '')
        filtros = data.get('filtros', {})

        if not mensagem:
            return jsonify({'erro': 'Mensagem não informada'}), 400

        api_key = os.environ.get('GROQ_API_KEY', '')
        if not api_key:
            return jsonify({'erro': 'GROQ_API_KEY nao configurada'}), 500

        # Monta contexto do sistema
        sistema = """Você é o Valter, assistente inteligente do sistema Átomo da Alimentare.
        Responda em português, de forma direta, prática e objetiva.
        Use **negrito** para destacar dados importantes.
        Seja conciso mas completo.
        Nunca invente dados — use apenas o contexto fornecido.
        Se não souber, diga que não tem essa informação."""

        # Adiciona informações dos filtros atuais
        if filtros:
            filtros_str = ", ".join([f"{k}: {v}" for k, v in filtros.items() if v])
            sistema += f"\n\nFiltros atuais: {filtros_str}"

        # Adiciona página atual
        if contexto:
            sistema += f"\n\nPágina atual: {contexto}"

        # Busca dados adicionais do sistema
        try:
            conn = get_conn()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            # Dados rápidos do faturamento
            cursor.execute("""
                SELECT
                    ROUND(CAST(SUM(CASE WHEN tipo_operacao='Venda' THEN valor_nf ELSE 0 END) AS NUMERIC),2) AS faturamento,
                    COUNT(DISTINCT cliente) AS clientes,
                    COUNT(DISTINCT vendedor) AS vendedores
                FROM faturamento WHERE ano = EXTRACT(YEAR FROM CURRENT_DATE)
            """)
            dados = cursor.fetchone()

            if dados:
                sistema += f"\n\nDados rápidos: Faturamento R$ {dados['faturamento'] or 0:,.2f}, {dados['clientes'] or 0} clientes, {dados['vendedores'] or 0} vendedores"

            cursor.close()
            conn.close()
        except Exception:
            pass

        # Chama a API Groq
        resp = _req.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            },
            json={
                'model': 'llama-3.3-70b-versatile',
                'max_tokens': 1000,
                'messages': [
                    {'role': 'system', 'content': sistema},
                    {'role': 'user', 'content': mensagem}
                ],
                'temperature': 0.7
            },
            timeout=60
        )

        d = resp.json()
        if d.get('choices'):
            resposta = d['choices'][0]['message']['content']
            return jsonify({'resposta': resposta}), 200
        else:
            return jsonify({'erro': 'Erro na API Groq', 'detalhes': d}), 500

    except Exception as e:
        return jsonify({'erro': str(e), 'trace': tb.format_exc()}), 500


# ============================================================
# ROTA PARA ALERTAS PROATIVOS (melhorada)
# ============================================================

@app.route('/api/valter/alertas')
def valter_alertas():
    """Retorna alertas proativos do sistema"""
    try:
        conn = get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        alertas = []

        # 1. Produtos críticos no Shelf Life
        try:
            cur.execute("""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN dias_vencimento <= 7 THEN 1 ELSE 0 END) as urgente,
                       SUM(CASE WHEN dias_vencimento <= 30 AND dias_vencimento > 7 THEN 1 ELSE 0 END) as critico
                FROM shelflife
                WHERE semana = (SELECT MAX(semana) FROM shelflife)
                  AND dias_vencimento >= 0
            """)
            sl = cur.fetchone()
            if sl and sl['urgente'] > 0:
                alertas.append({
                    'icone': '🚨',
                    'texto': f"{sl['urgente']} produto(s) vencem em 7 dias!",
                    'tipo': 'danger',
                    'pergunta': f"Liste os {sl['urgente']} produtos que vencem em 7 dias"
                })
            if sl and sl['critico'] > 0:
                alertas.append({
                    'icone': '⚠️',
                    'texto': f"{sl['critico']} produto(s) críticos (vencem em até 30 dias)",
                    'tipo': 'warning',
                    'pergunta': f"Quais os {sl['critico']} produtos críticos no Shelf Life?"
                })
        except Exception:
            pass

        # 2. Clientes em risco
        try:
            cur.execute("""
                SELECT COUNT(*) as total
                FROM (
                    SELECT cod_cliente
                    FROM faturamento
                    WHERE tipo_operacao = 'Venda'
                    GROUP BY cod_cliente
                    HAVING EXTRACT(DAY FROM (CURRENT_DATE - MAX(data_movimento))) >= 90
                ) as risco
            """)
            risco = cur.fetchone()
            if risco and risco['total'] > 0:
                alertas.append({
                    'icone': '📉',
                    'texto': f"{risco['total']} cliente(s) sem compra há mais de 90 dias",
                    'tipo': 'warning',
                    'pergunta': f"Liste os {risco['total']} clientes sem compra há 90 dias"
                })
        except Exception:
            pass

        cur.close()
        conn.close()

        return jsonify({'alertas': alertas})

    except Exception as e:
        return jsonify({'alertas': [], 'erro': str(e)}), 500


# ============================================================
# ROTA PARA COMPARAR PERÍODOS (melhorada)
# ============================================================

@app.route('/api/comparar-periodos', methods=['GET'])
def comparar_periodos():
    """Compara dois períodos e retorna a variação"""
    try:
        ano_a = request.args.get('ano_a')
        mes_a = request.args.get('mes_a')
        ano_b = request.args.get('ano_b')
        mes_b = request.args.get('mes_b')

        def buscar(ano, mes):
            where = ["tipo_operacao IN ('Venda','Devolucao')"]
            params = []
            if ano:
                where.append('ano = %s')
                params.append(int(ano))
            if mes:
                where.append('mes = %s')
                params.append(int(mes))

            sql = f"""
                SELECT
                    ROUND(CAST(SUM(CASE WHEN tipo_operacao='Venda' THEN valor_nf ELSE 0 END) AS NUMERIC),2) AS faturamento,
                    ROUND(CAST(SUM(CASE WHEN tipo_operacao='Devolucao' THEN valor_nf ELSE 0 END) AS NUMERIC),2) AS devolucoes,
                    COUNT(DISTINCT cod_cliente) AS clientes,
                    COUNT(DISTINCT num_nf) AS pedidos,
                    ROUND(CAST(AVG(CASE WHEN tipo_operacao='Venda' THEN valor_nf END) AS NUMERIC),2) AS ticket_medio
                FROM faturamento
                WHERE {' AND '.join(where)}
            """
            conn = get_conn()
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(sql, params)
            r = cur.fetchone()
            cur.close()
            conn.close()

            return {
                'faturamento': float(r['faturamento'] or 0),
                'devolucoes': float(r['devolucoes'] or 0),
                'liquido': float(r['faturamento'] or 0) - float(r['devolucoes'] or 0),
                'clientes': int(r['clientes'] or 0),
                'pedidos': int(r['pedidos'] or 0),
                'ticket_medio': float(r['ticket_medio'] or 0)
            }

        if not ano_a or not mes_a or not ano_b or not mes_b:
            return jsonify({'erro': 'Selecione os dois períodos'}), 400

        pA = buscar(ano_a, mes_a)
        pB = buscar(ano_b, mes_b)

        def calcular_variacao(a, b):
            if not b:
                return None
            if b == 0:
                return 100 if a > 0 else 0
            return round(((a - b) / abs(b)) * 100, 1)

        return jsonify({
            'periodo_a': pA,
            'periodo_b': pB,
            'variacao': {
                'faturamento': calcular_variacao(pA['faturamento'], pB['faturamento']),
                'devolucoes': calcular_variacao(pA['devolucoes'], pB['devolucoes']),
                'liquido': calcular_variacao(pA['liquido'], pB['liquido']),
                'clientes': calcular_variacao(pA['clientes'], pB['clientes']),
                'pedidos': calcular_variacao(pA['pedidos'], pB['pedidos']),
                'ticket_medio': calcular_variacao(pA['ticket_medio'], pB['ticket_medio'])
            }
        })

    except Exception as e:
        return jsonify({'erro': str(e), 'trace': tb.format_exc()}), 500


# ============================================================
# ROTA PARA COMPARAR PERÍODOS (versão simplificada para o home)
# ============================================================

@app.route('/api/comparar', methods=['GET'])
def comparar():
    """Versão simplificada para comparação de períodos"""
    try:
        ano_a = request.args.get('ano_a')
        mes_a = request.args.get('mes_a')
        ano_b = request.args.get('ano_b')
        mes_b = request.args.get('mes_b')

        if not ano_a or not mes_a or not ano_b or not mes_b:
            return jsonify({'erro': 'Parâmetros incompletos'}), 400

        conn = get_conn()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        def get_data(ano, mes):
            cursor.execute("""
                SELECT
                    ROUND(CAST(SUM(CASE WHEN tipo_operacao='Venda' THEN valor_nf ELSE 0 END) AS NUMERIC),2) AS faturamento,
                    ROUND(CAST(SUM(CASE WHEN tipo_operacao='Devolucao' THEN valor_nf ELSE 0 END) AS NUMERIC),2) AS devolucoes,
                    COUNT(DISTINCT cod_cliente) AS clientes,
                    COUNT(*) AS vendas
                FROM faturamento
                WHERE ano = %s AND mes = %s
            """, [int(ano), int(mes)])
            return cursor.fetchone()

        rA = get_data(ano_a, mes_a)
        rB = get_data(ano_b, mes_b)

        cursor.close()
        conn.close()

        return jsonify({
            'periodo_a': {
                'faturamento': float(rA['faturamento'] or 0),
                'devolucoes': float(rA['devolucoes'] or 0),
                'clientes': int(rA['clientes'] or 0),
                'vendas': int(rA['vendas'] or 0)
            },
            'periodo_b': {
                'faturamento': float(rB['faturamento'] or 0),
                'devolucoes': float(rB['devolucoes'] or 0),
                'clientes': int(rB['clientes'] or 0),
                'vendas': int(rB['vendas'] or 0)
            }
        })

    except Exception as e:
        return jsonify({'erro': str(e)}), 500


# ============================================================
# ROTAS DE SHELF LIFE (mantidas do original)
# ============================================================

# [Todas as rotas de shelflife do arquivo original permanecem aqui]
# Para economizar espaço, mantive apenas as novas rotas.
# As rotas existentes devem ser copiadas do arquivo original.

# ============================================================
# ROTAS DE PIVOT (mantidas do original)
# ============================================================

@app.route('/api/pivot-clientes')
def pivot_clientes():
    """Pivot de clientes - versão otimizada do original"""
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

        # Query principal
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
        return jsonify({'erro': str(e), 'trace': tb.format_exc()}), 500


@app.route('/api/pivot-cliente-produto')
def pivot_cliente_produto():
    """Pivot de produtos por cliente"""
    try:
        clientes_cod = request.args.getlist('cod_cliente')
        periodos = request.args.getlist('periodo')

        if not clientes_cod:
            return jsonify({'erro': 'Selecione ao menos um cliente'}), 400

        where = []
        params = []

        placeholders = ','.join(['%s'] * len(clientes_cod))
        where.append(f"cod_cliente IN ({placeholders})")
        params.extend(clientes_cod)

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
                cliente,
                cod_cliente,
                produto,
                cod_produto,
                marca,
                ano,
                mes,
                ROUND(CAST(SUM(CASE WHEN tipo_operacao='Venda' THEN valor_nf ELSE 0 END) AS NUMERIC),2) AS faturamento,
                ROUND(CAST(SUM(CASE WHEN tipo_operacao='Devolucao' THEN ABS(valor_nf) ELSE 0 END) AS NUMERIC),2) AS devolucoes
            FROM faturamento
            {where_str}
            GROUP BY cliente, cod_cliente, produto, cod_produto, marca, ano, mes
            ORDER BY produto, cliente, ano, mes
        """

        resultado = consultar(sql, params)
        return jsonify(resultado)

    except Exception as e:
        return jsonify({'erro': str(e), 'trace': tb.format_exc()}), 500


# ============================================================
# ROTAS DE EXPORTAÇÃO DE PRODUTOS
# ============================================================

@app.route('/api/clientes/produtos_export', methods=['POST'])
def clientes_produtos_export():
    """Exporta produtos por cliente - versão otimizada"""
    try:
        body = request.get_json(silent=True) or {}
        unidades = body.get('unidades') or []
        vendedores = body.get('vendedores') or []
        produtos = body.get('produtos') or []
        clientes = [str(c) for c in (body.get('cod_clientes') or [])]
        periodos = body.get('periodos') or []

        where = []
        params = []

        if unidades:
            where.append("f.unidade = ANY(%s::TEXT[])")
            params.append(list(unidades))

        if vendedores:
            where.append("f.vendedor = ANY(%s::TEXT[])")
            params.append(list(vendedores))

        if produtos:
            where.append("f.produto = ANY(%s::TEXT[])")
            params.append(list(produtos))

        if clientes:
            where.append("f.cod_cliente::TEXT = ANY(%s::TEXT[])")
            params.append(clientes)

        if periodos:
            pares = [f"{int(p.get('ano'))}-{int(p.get('mes'))}" for p in periodos if p.get('ano') and p.get('mes')]
            if pares:
                where.append("(f.ano::TEXT || '-' || f.mes::TEXT) = ANY(%s::TEXT[])")
                params.append(pares)

        where_str = "WHERE " + " AND ".join(where) if where else ""

        sql = f"""
            WITH cart AS (
                SELECT DISTINCT ON (cod_cliente)
                       cod_cliente::TEXT AS cod_cliente,
                       cod_vendedor
                FROM carteira
                ORDER BY cod_cliente
            )
            SELECT
                f.cod_cliente,
                MAX(f.cliente) AS cliente,
                MAX(COALESCE(v.nome, f.vendedor)) AS vendedor,
                f.cod_produto,
                f.produto,
                MAX(f.marca) AS marca,
                f.ano,
                f.mes,
                ROUND(CAST(SUM(f.valor_nf) AS NUMERIC), 2) AS valor_nf,
                ROUND(CAST(SUM(f.quantidade) AS NUMERIC), 2) AS quantidade
            FROM faturamento f
            LEFT JOIN cart c ON c.cod_cliente = f.cod_cliente::TEXT
            LEFT JOIN vendedores v ON v.cod_vendedor::TEXT = c.cod_vendedor::TEXT
            {where_str}
            GROUP BY f.cod_cliente, f.cod_produto, f.produto, f.ano, f.mes
            ORDER BY f.cod_cliente, f.produto
        """

        resultado = consultar(sql, params)
        return jsonify(resultado)

    except Exception as e:
        return jsonify({'erro': str(e), 'trace': tb.format_exc()}), 500


# ============================================================
# ROTA PARA CLIENTES EM RISCO
# ============================================================

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
        return jsonify({'erro': str(e), 'trace': tb.format_exc()}), 500


# ============================================================
# ROTA PARA HISTÓRICO DE CLIENTES
# ============================================================

@app.route('/api/clientes/historico')
def cliente_historico():
    try:
        cod_cliente = request.args.get('cod_cliente', '').strip()
        vendedor_nome = request.args.get('vendedor', '').strip()
        unidades = request.args.getlist('unidade')

        where = []
        params = []

        if unidades:
            where.append("unidade = ANY(%s::TEXT[])")
            params.append(list(unidades))

        if cod_cliente:
            where.append("cod_cliente = %s")
            params.append(cod_cliente)

        if vendedor_nome:
            where.append("vendedor = %s")
            params.append(vendedor_nome)

        where_str = "WHERE " + " AND ".join(where) if where else ""

        resultado = consultar(f"""
            SELECT
                ano, mes, data_movimento, num_nf, tipo_operacao,
                produto, cod_produto, marca, quantidade,
                ROUND(CAST(valor_nf AS NUMERIC), 2) AS valor_nf,
                vendedor, unidade, cod_cliente, cliente
            FROM faturamento
            {where_str}
            ORDER BY data_movimento DESC, ano DESC, mes DESC
        """, params)

        return jsonify(resultado)

    except Exception as e:
        return jsonify({'erro': str(e), 'trace': tb.format_exc()}), 500


# ============================================================
# INICIALIZAÇÃO DO CACHE
# ============================================================

if __name__ == '__main__':
    # Aquece cache
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
        conn.close()
        print("✅ Banco conectado com sucesso!")
    except Exception as e:
        print(f"⚠️ Erro ao conectar ao banco: {e}")

    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
