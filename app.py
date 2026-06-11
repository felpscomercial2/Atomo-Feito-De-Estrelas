from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
import psycopg2
import psycopg2.extras
import os
import re
import time
import json
import io
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
import base64

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

    cache_set(key, resultado)
    return jsonify(resultado)

@app.route('/api/faturamento-por-regiao')
def faturamento_por_regiao():
    key    = cache_key('faturamento-por-regiao', dict(request.args))
    cached = cache_get(key)
    if cached: return jsonify(cached)

    where, params = montar_filtros(request.args)
    and_or   = 'AND' if where else 'WHERE'
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

@app.route('/api/faturamento-por-uf')
def faturamento_por_uf():
    key    = cache_key('faturamento-por-uf', dict(request.args))
    cached = cache_get(key)
    if cached: return jsonify(cached)

    where, params = montar_filtros(request.args)
    and_or   = 'AND' if where else 'WHERE'
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

@app.route('/api/produtos-top')
def produtos_top():
    key    = cache_key('produtos-top', dict(request.args))
    cached = cache_get(key)
    if cached: return jsonify(cached)

    where, params = montar_filtros(request.args)
    limite   = int(request.args.get('limite', 20))
    and_or   = 'AND' if where else 'WHERE'
    resultado = consultar(f"""
        SELECT produto, cod_produto, marca,
            ROUND(CAST(SUM(valor_nf) AS NUMERIC), 2) AS faturamento,
            COUNT(*) AS qtd_vendas
        FROM faturamento {where} {and_or} tipo_operacao = 'Venda'
        GROUP BY produto, cod_produto, marca ORDER BY faturamento DESC LIMIT %s
    """, params + [limite])

    cache_set(key, resultado)
    return jsonify(resultado)

@app.route('/api/todos-produtos')
def todos_produtos():
    key = 'todos_produtos'
    cached = cache_get(key)
    if cached: return jsonify(cached)

    resultado = consultar("""
        SELECT DISTINCT produto, cod_produto, marca
        FROM faturamento
        WHERE produto IS NOT NULL AND produto != ''
        ORDER BY produto
    """)

    cache_set(key, resultado)
    return jsonify(resultado)

@app.route('/api/clientes-inativos')
def clientes_inativos():
    try:
        dias = int(request.args.get('dias', 30))
        limit = int(request.args.get('limit', 100))

        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT
                f.cod_cliente, f.cliente, f.vendedor, f.cod_vendedor,
                MAX(f.data_movimento::DATE) AS ultima_compra,
                (CURRENT_DATE - MAX(f.data_movimento::DATE))::INT AS dias_sem_compra,
                ROUND(SUM(f.valor_nf)::NUMERIC, 2) AS fat_total,
                COUNT(DISTINCT f.num_nf) AS num_pedidos
            FROM faturamento f
            WHERE f.tipo_operacao='Venda' AND f.cliente IS NOT NULL
            GROUP BY f.cod_cliente, f.cliente, f.vendedor, f.cod_vendedor
            HAVING (CURRENT_DATE - MAX(f.data_movimento::DATE))::INT >= %s
            ORDER BY dias_sem_compra DESC
            LIMIT %s
        """, [dias, limit])
        cols = [d[0] for d in cur.description]
        rows = []
        for r in cur.fetchall():
            row = dict(zip(cols, r))
            row['dias_sem_compra'] = int(row['dias_sem_compra'] or 0)
            row['fat_total']       = float(row['fat_total'] or 0)
            row['num_pedidos']     = int(row['num_pedidos'] or 0)
            rows.append(row)
        cur.close(); conn.close()
        return jsonify({'clientes': rows, 'total': len(rows), 'dias_corte': dias})
    except Exception as e:
        import traceback
        return jsonify({'erro': str(e), 'trace': traceback.format_exc()}), 500

# ============================================================
#  COMPARAÇÃO DE PERÍODOS
# ============================================================
@app.route('/api/comparar-periodos')
def comparar_periodos():
    try:
        ano_a = request.args.get('ano_a')
        mes_a = request.args.get('mes_a')
        ano_b = request.args.get('ano_b')
        mes_b = request.args.get('mes_b')

        def buscar(ano, mes):
            where = ["tipo_operacao IN ('Venda','Devolucao')"]
            params = []
            if ano: where.append('ano = %s'); params.append(int(ano))
            if mes: where.append('mes = %s'); params.append(int(mes))
            sql = """SELECT
                ROUND(SUM(CASE WHEN tipo_operacao='Venda'     THEN valor_nf ELSE 0 END)::NUMERIC,2),
                ROUND(SUM(CASE WHEN tipo_operacao='Devolucao' THEN valor_nf ELSE 0 END)::NUMERIC,2),
                COUNT(DISTINCT cod_cliente),
                COUNT(DISTINCT num_nf),
                ROUND(AVG(CASE WHEN tipo_operacao='Venda' THEN valor_nf END)::NUMERIC,2)
                FROM faturamento WHERE """ + ' AND '.join(where)
            conn = get_conn(); cur = conn.cursor()
            cur.execute(sql, params)
            r = cur.fetchone(); cur.close(); conn.close()
            fat = float(r[0] or 0); dev = float(r[1] or 0)
            return {'faturamento': fat, 'devolucoes': dev, 'liquido': fat + dev,
                    'clientes': int(r[2] or 0), 'pedidos': int(r[3] or 0),
                    'ticket_medio': float(r[4] or 0)}

        pA = buscar(ano_a, mes_a)
        pB = buscar(ano_b, mes_b)

        def var(a, b):
            if not b: return None
            return round((a - b) / abs(b) * 100, 1)

        return jsonify({
            'periodo_a': pA, 'periodo_b': pB,
            'variacao': {k: var(pA[k], pB[k]) for k in pA}
        })
    except Exception as e:
        return jsonify({'erro': str(e)}), 500


# ============================================================
# ROTAS DE COMPRAS
# ============================================================

@app.route('/api/compras/upload', methods=['POST'])
def upload_compras():
    """Upload de planilha Excel de compras"""
    try:
        data = request.get_json()
        file_name = data.get('fileName', 'compras.xlsx')
        file_data_b64 = data.get('fileData', '')
        user_id = data.get('userId', 1)
        
        if not file_data_b64:
            return jsonify({'erro': 'Arquivo não fornecido'}), 400
        
        file_data = base64.b64decode(file_data_b64)
        wb = load_workbook(io.BytesIO(file_data))
        ws = wb.active
        
        items = []
        headers = {}
        
        for col_idx, cell in enumerate(ws[1], 1):
            headers[cell.value] = col_idx
        
        for row_idx in range(2, ws.max_row + 1):
            row_data = {}
            for col_idx in range(1, ws.max_column + 1):
                cell = ws.cell(row_idx, col_idx)
                header_name = ws.cell(1, col_idx).value
                row_data[header_name] = cell.value
            items.append(row_data)
        
        if not items:
            return jsonify({'erro': 'Planilha vazia'}), 400
        
        conn = get_conn()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO purchases_uploads (userId, fileName, totalItems)
            VALUES (%s, %s, %s)
            RETURNING id
        """, (user_id, file_name, len(items)))
        
        upload_id = cursor.fetchone()[0]
        
        for item in items:
            cursor.execute("""
                INSERT INTO purchase_items (
                    uploadId, carimboDataHora, enderecoEmail, base, nomeVendedor,
                    codigoProduto, descricaoProduto, quantidadeMediaVenda, marca,
                    temEstoque, previsaoChegada, faltaReincidente, produtoNovo, observacoes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                upload_id,
                str(item.get('Carimbo de data/hora', '')),
                str(item.get('Endereço de e-mail', '')),
                str(item.get('BASE', '')),
                str(item.get('Nome vendedor ', '')),
                str(item.get('Código produto', '')),
                str(item.get('Descrição produto (o mais próximo do sistema)', '')),
                str(item.get('Quantidade media de venda projetada apenas em UNIDADES\n', '')),
                str(item.get('Marca ', '')),
                str(item.get('Tem estoque ', '')),
                str(item.get('Previsão de chegada ', '')),
                str(item.get('Essa Falta é reincidente ? ou seja esse produto já ficou em falta outras vezes?', '')),
                str(item.get('Produto novo ?', '')),
                str(item.get('Observações ( se for produto novo colocar a média de venda)\n', ''))
            ))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'uploadId': upload_id,
            'totalItems': len(items),
            'message': f'Planilha carregada com {len(items)} itens'
        }), 201
        
    except Exception as e:
        import traceback
        return jsonify({
            'erro': str(e),
            'trace': traceback.format_exc()
        }), 500

@app.route('/api/compras/uploads', methods=['GET'])
def listar_uploads():
    """Lista todos os uploads de compras"""
    try:
        user_id = request.args.get('userId', 1)
        
        conn = get_conn()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        cursor.execute("""
            SELECT id, userId, fileName, totalItems, uploadDate, createdAt
            FROM purchases_uploads
            WHERE userId = %s
            ORDER BY uploadDate DESC
        """, (user_id,))
        
        uploads = []
        for row in cursor.fetchall():
            upload = dict(row)
            if hasattr(upload['uploadDate'], 'isoformat'):
                upload['uploadDate'] = upload['uploadDate'].isoformat()
            if hasattr(upload['createdAt'], 'isoformat'):
                upload['createdAt'] = upload['createdAt'].isoformat()
            uploads.append(upload)
        
        cursor.close()
        conn.close()
        
        return jsonify(uploads), 200
        
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

@app.route('/api/compras/upload/<int:upload_id>', methods=['GET'])
def obter_upload(upload_id):
    """Obtém detalhes de um upload específico"""
    try:
        conn = get_conn()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        cursor.execute("""
            SELECT id, userId, fileName, totalItems, uploadDate, createdAt
            FROM purchases_uploads
            WHERE id = %s
        """, (upload_id,))
        
        upload_row = cursor.fetchone()
        if not upload_row:
            return jsonify({'erro': 'Upload não encontrado'}), 404
        
        upload = dict(upload_row)
        if hasattr(upload['uploadDate'], 'isoformat'):
            upload['uploadDate'] = upload['uploadDate'].isoformat()
        if hasattr(upload['createdAt'], 'isoformat'):
            upload['createdAt'] = upload['createdAt'].isoformat()
        
        cursor.execute("""
            SELECT * FROM purchase_items WHERE uploadId = %s
            ORDER BY id
        """, (upload_id,))
        
        items = []
        for row in cursor.fetchall():
            item = dict(row)
            if hasattr(item.get('createdAt'), 'isoformat'):
                item['createdAt'] = item['createdAt'].isoformat()
            items.append(item)
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'upload': upload,
            'items': items
        }), 200
        
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

@app.route('/api/compras/comparar/<int:upload_id>', methods=['GET'])
def comparar_uploads(upload_id):
    """Compara upload atual com o anterior"""
    try:
        conn = get_conn()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        cursor.execute("""
            SELECT userId FROM purchases_uploads WHERE id = %s
        """, (upload_id,))
        
        upload_row = cursor.fetchone()
        if not upload_row:
            return jsonify({'erro': 'Upload não encontrado'}), 404
        
        user_id = upload_row['userId']
        
        cursor.execute("""
            SELECT id FROM purchases_uploads
            WHERE userId = %s
            ORDER BY uploadDate DESC
        """, (user_id,))
        
        all_uploads = [r['id'] for r in cursor.fetchall()]
        
        if upload_id not in all_uploads:
            return jsonify({'erro': 'Upload não encontrado'}), 404
        
        current_index = all_uploads.index(upload_id)
        
        cursor.execute("""
            SELECT * FROM purchase_items WHERE uploadId = %s
        """, (upload_id,))
        
        current_items = [dict(r) for r in cursor.fetchall()]
        current_total = len(current_items)
        
        if current_index >= len(all_uploads) - 1:
            return jsonify({
                'currentTotal': current_total,
                'previousTotal': 0,
                'newProducts': current_items,
                'removedProducts': []
            }), 200
        
        previous_upload_id = all_uploads[current_index + 1]
        cursor.execute("""
            SELECT * FROM purchase_items WHERE uploadId = %s
        """, (previous_upload_id,))
        
        previous_items = [dict(r) for r in cursor.fetchall()]
        previous_total = len(previous_items)
        
        current_codes = set()
        for item in current_items:
            code = (item.get('codigoProduto') or '').strip().lower()
            desc = (item.get('descricaoProduto') or '').strip().lower()
            key = code or desc or ''
            if key:
                current_codes.add(key)
        
        previous_codes = set()
        for item in previous_items:
            code = (item.get('codigoProduto') or '').strip().lower()
            desc = (item.get('descricaoProduto') or '').strip().lower()
            key = code or desc or ''
            if key:
                previous_codes.add(key)
        
        new_products = []
        for item in current_items:
            code = (item.get('codigoProduto') or '').strip().lower()
            desc = (item.get('descricaoProduto') or '').strip().lower()
            key = code or desc or ''
            if key and key not in previous_codes:
                new_products.append(item)
        
        removed_products = []
        for item in previous_items:
            code = (item.get('codigoProduto') or '').strip().lower()
            desc = (item.get('descricaoProduto') or '').strip().lower()
            key = code or desc or ''
            if key and key not in current_codes:
                removed_products.append(item)
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'currentTotal': current_total,
            'previousTotal': previous_total,
            'newProducts': new_products,
            'removedProducts': removed_products
        }), 200
        
    except Exception as e:
        import traceback
        return jsonify({
            'erro': str(e),
            'trace': traceback.format_exc()
        }), 500

@app.route('/api/compras/upload/<int:upload_id>', methods=['DELETE'])
def deletar_upload(upload_id):
    """Deleta um upload e seus itens"""
    try:
        conn = get_conn()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM purchase_items WHERE uploadId = %s", (upload_id,))
        cursor.execute("DELETE FROM purchases_uploads WHERE id = %s", (upload_id,))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Upload deletado com sucesso'}), 200
        
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

@app.route('/api/compras/export/<int:upload_id>', methods=['GET'])
def exportar_upload(upload_id):
    """Exporta upload para Excel"""
    try:
        conn = get_conn()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        cursor.execute("""
            SELECT * FROM purchase_items WHERE uploadId = %s
            ORDER BY id
        """, (upload_id,))
        
        items = [dict(r) for r in cursor.fetchall()]
        
        if not items:
            return jsonify({'erro': 'Nenhum item para exportar'}), 404
        
        wb = Workbook()
        ws = wb.active
        ws.title = "Compras"
        
        headers = [
            'Carimbo de data/hora',
            'Endereço de e-mail',
            'BASE',
            'Nome vendedor',
            'Código produto',
            'Descrição produto',
            'Quantidade média de venda',
            'Marca',
            'Tem estoque',
            'Previsão de chegada',
            'Falta reincidente',
            'Produto novo',
            'Observações'
        ]
        
        for col_idx, header in enumerate(headers, 1):
            cell = ws.cell(1, col_idx)
            cell.value = header
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill(start_color="015FB8", end_color="015FB8", fill_type="solid")
            cell.alignment = Alignment(horizontal="center", vertical="center")
        
        for row_idx, item in enumerate(items, 2):
            ws.cell(row_idx, 1).value = item.get('carimboDataHora')
            ws.cell(row_idx, 2).value = item.get('enderecoEmail')
            ws.cell(row_idx, 3).value = item.get('base')
            ws.cell(row_idx, 4).value = item.get('nomeVendedor')
            ws.cell(row_idx, 5).value = item.get('codigoProduto')
            ws.cell(row_idx, 6).value = item.get('descricaoProduto')
            ws.cell(row_idx, 7).value = item.get('quantidadeMediaVenda')
            ws.cell(row_idx, 8).value = item.get('marca')
            ws.cell(row_idx, 9).value = item.get('temEstoque')
            ws.cell(row_idx, 10).value = item.get('previsaoChegada')
            ws.cell(row_idx, 11).value = item.get('faltaReincidente')
            ws.cell(row_idx, 12).value = item.get('produtoNovo')
            ws.cell(row_idx, 13).value = item.get('observacoes')
        
        for col_idx in range(1, len(headers) + 1):
            ws.column_dimensions[chr(64 + col_idx)].width = 20
        
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        
        cursor.close()
        conn.close()
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'compras_export_{upload_id}.xlsx'
        )
        
    except Exception as e:
        import traceback
        return jsonify({
            'erro': str(e),
            'trace': traceback.format_exc()
        }), 500


if __name__ == '__main__':
    print("Atomo API iniciando...")
    app.run(debug=False, host='0.0.0.0', port=5000)
