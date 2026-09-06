from flask import Flask, jsonify, request, send_file, g
from flask_cors import CORS
import os
import datetime
import json
import io

app = Flask(__name__)
CORS(app)

# ============================================================
# ROTAS PRINCIPAIS
# ============================================================

@app.route('/')
def home():
    return jsonify({"status": "online", "mensagem": "API Átomo funcionando!"})

@app.route('/ping')
def ping():
    return jsonify({"status": "pong", "uptime": "ok"})

# ============================================================
# API FILTROS
# ============================================================

@app.route('/api/filtros')
def filtros():
    return jsonify({
        'anos': [2024, 2025, 2026],
        'meses': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        'unidades': ['PR', 'RS', 'SC', 'SP'],
        'ufs': ['PR', 'RS', 'SC', 'SP', 'MG', 'RJ', 'GO', 'BA'],
        'marcas': ['Marca A', 'Marca B', 'Marca C', 'Marca D'],
        'tipos': ['Venda', 'Devolucao', 'Bonificacao'],
        'vendedores': ['João Silva', 'Maria Santos', 'Pedro Costa', 'Ana Oliveira']
    })

# ============================================================
# API KPIs
# ============================================================

@app.route('/api/kpis')
def kpis():
    return jsonify({
        'faturamento': 1250000.00,
        'devolucoes': 85000.00,
        'bonificacoes': 12000.00,
        'ticket_medio': 3650.50,
        'total_clientes': 342,
        'qtd_vendas': 342
    })

# ============================================================
# API DASHBOARD
# ============================================================

@app.route('/api/dashboard')
def dashboard():
    return jsonify({
        'kpis': {
            'faturamento': 1250000.00,
            'devolucoes': 85000.00,
            'bonificacoes': 12000.00,
            'ticket_medio': 3650.50,
            'total_clientes': 342,
            'qtd_vendas': 342
        },
        'mensal': [
            {'ano': 2026, 'mes': 1, 'faturamento': 98000.00, 'devolucoes': 5000.00},
            {'ano': 2026, 'mes': 2, 'faturamento': 112000.00, 'devolucoes': 4000.00},
            {'ano': 2026, 'mes': 3, 'faturamento': 145000.00, 'devolucoes': 8000.00},
            {'ano': 2026, 'mes': 4, 'faturamento': 132000.00, 'devolucoes': 6000.00},
            {'ano': 2026, 'mes': 5, 'faturamento': 158000.00, 'devolucoes': 7500.00},
            {'ano': 2026, 'mes': 6, 'faturamento': 175000.00, 'devolucoes': 9000.00}
        ],
        'unidade': [
            {'unidade': 'PR', 'faturamento': 450000.00, 'devolucoes': 25000.00, 'clientes': 120},
            {'unidade': 'RS', 'faturamento': 380000.00, 'devolucoes': 22000.00, 'clientes': 98},
            {'unidade': 'SC', 'faturamento': 250000.00, 'devolucoes': 18000.00, 'clientes': 75},
            {'unidade': 'SP', 'faturamento': 170000.00, 'devolucoes': 20000.00, 'clientes': 49}
        ],
        'vendedores': [
            {'vendedor': 'João Silva', 'faturamento': 350000.00, 'clientes': 85},
            {'vendedor': 'Maria Santos', 'faturamento': 280000.00, 'clientes': 72},
            {'vendedor': 'Pedro Costa', 'faturamento': 220000.00, 'clientes': 58},
            {'vendedor': 'Ana Oliveira', 'faturamento': 180000.00, 'clientes': 50}
        ],
        'marcas': [
            {'marca': 'Nestlé', 'faturamento': 320000.00, 'clientes': 95},
            {'marca': 'Unilever', 'faturamento': 250000.00, 'clientes': 78},
            {'marca': 'Bunge', 'faturamento': 200000.00, 'clientes': 62},
            {'marca': 'Cargill', 'faturamento': 150000.00, 'clientes': 48}
        ]
    })

# ============================================================
# API TOP VENDEDORES
# ============================================================

@app.route('/api/top-vendedores')
def top_vendedores():
    return jsonify([
        {'vendedor': 'João Silva', 'faturamento': 350000.00, 'clientes': 85, 'unidades': 3, 'qtd_vendas': 95},
        {'vendedor': 'Maria Santos', 'faturamento': 280000.00, 'clientes': 72, 'unidades': 2, 'qtd_vendas': 78},
        {'vendedor': 'Pedro Costa', 'faturamento': 220000.00, 'clientes': 58, 'unidades': 2, 'qtd_vendas': 62},
        {'vendedor': 'Ana Oliveira', 'faturamento': 180000.00, 'clientes': 50, 'unidades': 1, 'qtd_vendas': 55}
    ])

# ============================================================
# API TOP PRODUTOS
# ============================================================

@app.route('/api/top-produtos')
def top_produtos():
    return jsonify([
        {'produto': 'Farinha de Trigo', 'marca': 'Bunge', 'faturamento': 85000.00, 'quantidade': 1200},
        {'produto': 'Óleo de Soja', 'marca': 'Cargill', 'faturamento': 72000.00, 'quantidade': 980},
        {'produto': 'Leite Condensado', 'marca': 'Nestlé', 'faturamento': 65000.00, 'quantidade': 850},
        {'produto': 'Café Solúvel', 'marca': 'Nestlé', 'faturamento': 58000.00, 'quantidade': 620},
        {'produto': 'Margarina', 'marca': 'Unilever', 'faturamento': 48000.00, 'quantidade': 750},
        {'produto': 'Fermento Biológico', 'marca': 'Fleischmann', 'faturamento': 42000.00, 'quantidade': 380}
    ])

# ============================================================
# API FATURAMENTO POR MARCA
# ============================================================

@app.route('/api/faturamento-por-marca')
def faturamento_por_marca():
    return jsonify([
        {'marca': 'Nestlé', 'faturamento': 320000.00, 'clientes': 95},
        {'marca': 'Unilever', 'faturamento': 250000.00, 'clientes': 78},
        {'marca': 'Bunge', 'faturamento': 200000.00, 'clientes': 62},
        {'marca': 'Cargill', 'faturamento': 150000.00, 'clientes': 48},
        {'marca': 'Fleischmann', 'faturamento': 98000.00, 'clientes': 35}
    ])

# ============================================================
# API FATURAMENTO POR REGIAO
# ============================================================

@app.route('/api/faturamento-por-regiao')
def faturamento_por_regiao():
    return jsonify([
        {'regiao': 'Sul', 'faturamento': 680000.00, 'clientes': 195},
        {'regiao': 'Sudeste', 'faturamento': 420000.00, 'clientes': 120},
        {'regiao': 'Centro-Oeste', 'faturamento': 150000.00, 'clientes': 27}
    ])

# ============================================================
# API FATURAMENTO POR UNIDADE
# ============================================================

@app.route('/api/faturamento-por-unidade')
def faturamento_por_unidade():
    return jsonify([
        {'unidade': 'PR', 'faturamento': 450000.00, 'devolucoes': 25000.00, 'bonificacoes': 5000.00, 'clientes': 120},
        {'unidade': 'RS', 'faturamento': 380000.00, 'devolucoes': 22000.00, 'bonificacoes': 4000.00, 'clientes': 98},
        {'unidade': 'SC', 'faturamento': 250000.00, 'devolucoes': 18000.00, 'bonificacoes': 2000.00, 'clientes': 75},
        {'unidade': 'SP', 'faturamento': 170000.00, 'devolucoes': 20000.00, 'bonificacoes': 1000.00, 'clientes': 49}
    ])

# ============================================================
# API FATURAMENTO POR UF
# ============================================================

@app.route('/api/faturamento-por-uf')
def faturamento_por_uf():
    return jsonify([
        {'uf': 'PR', 'faturamento': 450000.00, 'clientes': 120},
        {'uf': 'RS', 'faturamento': 380000.00, 'clientes': 98},
        {'uf': 'SC', 'faturamento': 250000.00, 'clientes': 75},
        {'uf': 'SP', 'faturamento': 170000.00, 'clientes': 49},
        {'uf': 'MG', 'faturamento': 120000.00, 'clientes': 38},
        {'uf': 'RJ', 'faturamento': 85000.00, 'clientes': 28}
    ])

# ============================================================
# API FATURAMENTO POR CIDADE
# ============================================================

@app.route('/api/faturamento-por-cidade')
def faturamento_por_cidade():
    return jsonify([
        {'cidade': 'Curitiba', 'uf': 'PR', 'faturamento': 280000.00, 'clientes': 72},
        {'cidade': 'Porto Alegre', 'uf': 'RS', 'faturamento': 220000.00, 'clientes': 58},
        {'cidade': 'Florianópolis', 'uf': 'SC', 'faturamento': 150000.00, 'clientes': 42},
        {'cidade': 'São Paulo', 'uf': 'SP', 'faturamento': 120000.00, 'clientes': 35},
        {'cidade': 'Belo Horizonte', 'uf': 'MG', 'faturamento': 80000.00, 'clientes': 25}
    ])

# ============================================================
# API FATURAMENTO MENSAL
# ============================================================

@app.route('/api/faturamento-mensal')
def faturamento_mensal():
    return jsonify([
        {'ano': 2026, 'mes': 1, 'faturamento': 98000.00, 'devolucoes': 5000.00, 'bonificacoes': 500.00},
        {'ano': 2026, 'mes': 2, 'faturamento': 112000.00, 'devolucoes': 4000.00, 'bonificacoes': 600.00},
        {'ano': 2026, 'mes': 3, 'faturamento': 145000.00, 'devolucoes': 8000.00, 'bonificacoes': 800.00},
        {'ano': 2026, 'mes': 4, 'faturamento': 132000.00, 'devolucoes': 6000.00, 'bonificacoes': 700.00},
        {'ano': 2026, 'mes': 5, 'faturamento': 158000.00, 'devolucoes': 7500.00, 'bonificacoes': 900.00},
        {'ano': 2026, 'mes': 6, 'faturamento': 175000.00, 'devolucoes': 9000.00, 'bonificacoes': 1000.00}
    ])

# ============================================================
# API TOP CLIENTES
# ============================================================

@app.route('/api/top-clientes')
def top_clientes():
    return jsonify([
        {'cliente': 'Supermercado Real', 'faturamento': 85000.00, 'qtd_vendas': 12},
        {'cliente': 'Atacadão Distribuidora', 'faturamento': 72000.00, 'qtd_vendas': 8},
        {'cliente': 'Mercado Central', 'faturamento': 65000.00, 'qtd_vendas': 15},
        {'cliente': 'Distribuidora Alfa', 'faturamento': 58000.00, 'qtd_vendas': 6},
        {'cliente': 'Supermercado Bom Preço', 'faturamento': 48000.00, 'qtd_vendas': 10}
    ])

# ============================================================
# API RESPOSTA CARTEIRA
# ============================================================

@app.route('/api/resumo-carteira')
def resumo_carteira():
    return jsonify({
        'total_carteira': 342,
        'total_codigos': 350,
        'margem_media': 28.5
    })

# ============================================================
# API TODOS PRODUTOS
# ============================================================

@app.route('/api/todos-produtos')
def todos_produtos():
    return jsonify([
        {'produto': 'Farinha de Trigo', 'cod_produto': '001', 'marca': 'Bunge'},
        {'produto': 'Óleo de Soja', 'cod_produto': '002', 'marca': 'Cargill'},
        {'produto': 'Leite Condensado', 'cod_produto': '003', 'marca': 'Nestlé'},
        {'produto': 'Café Solúvel', 'cod_produto': '004', 'marca': 'Nestlé'},
        {'produto': 'Margarina', 'cod_produto': '005', 'marca': 'Unilever'},
        {'produto': 'Fermento Biológico', 'cod_produto': '006', 'marca': 'Fleischmann'},
        {'produto': 'Açúcar Refinado', 'cod_produto': '007', 'marca': 'União'},
        {'produto': 'Arroz Branco', 'cod_produto': '008', 'marca': 'Tio João'},
        {'produto': 'Feijão Preto', 'cod_produto': '009', 'marca': 'Camil'},
        {'produto': 'Macarrão', 'cod_produto': '010', 'marca': 'Adria'}
    ])

# ============================================================
# API CLIENTES EM RISCO
# ============================================================

@app.route('/api/clientes-em-risco')
def clientes_em_risco():
    dias = request.args.get('dias', 60)
    return jsonify({
        'clientes': [
            {'cod_cliente': '001', 'cliente': 'Supermercado Estrela', 'vendedor': 'João Silva', 'ultima_compra': '2025-01-15', 'dias_sem_compra': 120, 'fat_total': 45000.00, 'num_pedidos': 8},
            {'cod_cliente': '002', 'cliente': 'Mercado do Bairro', 'vendedor': 'Maria Santos', 'ultima_compra': '2025-02-20', 'dias_sem_compra': 85, 'fat_total': 32000.00, 'num_pedidos': 5},
            {'cod_cliente': '003', 'cliente': 'Distribuidora Sul', 'vendedor': 'Pedro Costa', 'ultima_compra': '2025-03-10', 'dias_sem_compra': 65, 'fat_total': 28000.00, 'num_pedidos': 4},
            {'cod_cliente': '004', 'cliente': 'Atacado do Centro', 'vendedor': 'Ana Oliveira', 'ultima_compra': '2025-04-05', 'dias_sem_compra': 45, 'fat_total': 22000.00, 'num_pedidos': 3},
            {'cod_cliente': '005', 'cliente': 'Supermercado Família', 'vendedor': 'João Silva', 'ultima_compra': '2025-05-12', 'dias_sem_compra': 32, 'fat_total': 18000.00, 'num_pedidos': 2}
        ],
        'total': 5,
        'dias_corte': int(dias)
    })

# ============================================================
# API PIVOT CLIENTES
# ============================================================

@app.route('/api/pivot-clientes')
def pivot_clientes():
    return jsonify([
        {'cod_cliente': '001', 'cliente': 'Supermercado Real', 'vendedor': 'João Silva', 'unidade': 'PR', 'ano': 2026, 'mes': 1, 'faturamento': 12000.00, 'devolucoes': 500.00},
        {'cod_cliente': '001', 'cliente': 'Supermercado Real', 'vendedor': 'João Silva', 'unidade': 'PR', 'ano': 2026, 'mes': 2, 'faturamento': 15000.00, 'devolucoes': 600.00},
        {'cod_cliente': '001', 'cliente': 'Supermercado Real', 'vendedor': 'João Silva', 'unidade': 'PR', 'ano': 2026, 'mes': 3, 'faturamento': 18000.00, 'devolucoes': 700.00},
        {'cod_cliente': '002', 'cliente': 'Atacadão Distribuidora', 'vendedor': 'Maria Santos', 'unidade': 'RS', 'ano': 2026, 'mes': 1, 'faturamento': 8000.00, 'devolucoes': 300.00},
        {'cod_cliente': '002', 'cliente': 'Atacadão Distribuidora', 'vendedor': 'Maria Santos', 'unidade': 'RS', 'ano': 2026, 'mes': 2, 'faturamento': 10000.00, 'devolucoes': 400.00}
    ])

# ============================================================
# API PIVOT CLIENTE PRODUTO
# ============================================================

@app.route('/api/pivot-cliente-produto')
def pivot_cliente_produto():
    return jsonify([
        {'cliente': 'Supermercado Real', 'cod_cliente': '001', 'produto': 'Farinha de Trigo', 'cod_produto': '001', 'marca': 'Bunge', 'ano': 2026, 'mes': 1, 'faturamento': 5000.00, 'devolucoes': 200.00},
        {'cliente': 'Supermercado Real', 'cod_cliente': '001', 'produto': 'Óleo de Soja', 'cod_produto': '002', 'marca': 'Cargill', 'ano': 2026, 'mes': 1, 'faturamento': 4000.00, 'devolucoes': 150.00},
        {'cliente': 'Atacadão Distribuidora', 'cod_cliente': '002', 'produto': 'Leite Condensado', 'cod_produto': '003', 'marca': 'Nestlé', 'ano': 2026, 'mes': 1, 'faturamento': 6000.00, 'devolucoes': 200.00}
    ])

# ============================================================
# API VENDEDORES POR PRODUTO
# ============================================================

@app.route('/api/vendedores-por-produto')
def vendedores_por_produto():
    return jsonify(['João Silva', 'Maria Santos', 'Pedro Costa', 'Ana Oliveira'])

# ============================================================
# API TODOS CLIENTES
# ============================================================

@app.route('/api/todos-clientes')
def todos_clientes():
    return jsonify([
        {'cliente': 'Supermercado Real', 'cod_cliente': '001'},
        {'cliente': 'Atacadão Distribuidora', 'cod_cliente': '002'},
        {'cliente': 'Mercado Central', 'cod_cliente': '003'},
        {'cliente': 'Distribuidora Alfa', 'cod_cliente': '004'},
        {'cliente': 'Supermercado Bom Preço', 'cod_cliente': '005'}
    ])

# ============================================================
# API CLIENTES HISTORICO
# ============================================================

@app.route('/api/clientes/historico')
def clientes_historico():
    return jsonify([
        {'ano': 2026, 'mes': 1, 'data_movimento': '2026-01-15', 'num_nf': '001', 'tipo_operacao': 'Venda', 'produto': 'Farinha de Trigo', 'cod_produto': '001', 'marca': 'Bunge', 'quantidade': 100, 'valor_nf': 5000.00, 'vendedor': 'João Silva', 'unidade': 'PR', 'cod_cliente': '001', 'cliente': 'Supermercado Real'},
        {'ano': 2026, 'mes': 2, 'data_movimento': '2026-02-20', 'num_nf': '002', 'tipo_operacao': 'Venda', 'produto': 'Óleo de Soja', 'cod_produto': '002', 'marca': 'Cargill', 'quantidade': 80, 'valor_nf': 4000.00, 'vendedor': 'João Silva', 'unidade': 'PR', 'cod_cliente': '001', 'cliente': 'Supermercado Real'}
    ])

# ============================================================
# API COMPRAS
# ============================================================

@app.route('/api/compras/snapshots')
def compras_snapshots():
    return jsonify({
        'snapshots': [
            {'id': 1, 'base': 'PR', 'uploaddate': '06/09/2026 10:30', 'totalitems': 45},
            {'id': 2, 'base': 'RS', 'uploaddate': '05/09/2026 14:20', 'totalitems': 32}
        ]
    })

@app.route('/api/compras/listar')
def compras_listar():
    return jsonify({
        'items': [
            {'codigoProduto': '001', 'descricaoProduto': 'Farinha de Trigo', 'quantidadeMediaVenda': '100', 'marca': 'Bunge'},
            {'codigoProduto': '002', 'descricaoProduto': 'Óleo de Soja', 'quantidadeMediaVenda': '80', 'marca': 'Cargill'},
            {'codigoProduto': '003', 'descricaoProduto': 'Leite Condensado', 'quantidadeMediaVenda': '50', 'marca': 'Nestlé'}
        ],
        'codigosAnteriores': ['001', '002']
    })

# ============================================================
# API SHELF LIFE
# ============================================================

@app.route('/api/shelflife/verificar-acesso', methods=['POST'])
def shelflife_verificar_acesso():
    data = request.get_json(force=True)
    email = str(data.get('email', '')).strip().lower()
    emails_autorizados = ['comercial2@reforpan.com.br', 'comercial3@esdel.com.br', 'comercial1@esdel.com']
    autorizado = email in [e.lower() for e in emails_autorizados]
    return jsonify({'autorizado': autorizado, 'email': email})

@app.route('/api/shelflife/semanas')
def shelflife_semanas():
    return jsonify([
        {'semana': '2026-09-06', 'unidade': 'PR', 'total': 45},
        {'semana': '2026-08-30', 'unidade': 'PR', 'total': 38},
        {'semana': '2026-09-06', 'unidade': 'RS', 'total': 32}
    ])

@app.route('/api/shelflife/listar')
def shelflife_listar():
    return jsonify([
        {'id': 1, 'cod_produto': '001', 'cod_sl': 'SL-001', 'produto': 'Farinha de Trigo', 'marca': 'Bunge', 'unidade': 'UN', 'quantidade_log': 150, 'quantidade_atual': 120, 'validade': '2026-12-31', 'dias_vencimento': 25, 'status': 'CRITICO', 'is_sl': True, 'vendedor': 'João Silva', 'acao': 'Promocao de Preco'},
        {'id': 2, 'cod_produto': '002', 'cod_sl': '', 'produto': 'Óleo de Soja', 'marca': 'Cargill', 'unidade': 'L', 'quantidade_log': 200, 'quantidade_atual': 180, 'validade': '2026-11-15', 'dias_vencimento': 45, 'status': 'ATENCAO', 'is_sl': False, 'vendedor': 'Maria Santos', 'acao': ''},
        {'id': 3, 'cod_produto': '003', 'cod_sl': '', 'produto': 'Leite Condensado', 'marca': 'Nestlé', 'unidade': 'L', 'quantidade_log': 100, 'quantidade_atual': 85, 'validade': '2026-10-01', 'dias_vencimento': 80, 'status': 'OK', 'is_sl': False, 'vendedor': 'Pedro Costa', 'acao': ''}
    ])

@app.route('/api/shelflife/atualizar', methods=['POST'])
def shelflife_atualizar():
    return jsonify({'ok': True, 'alteracoes': ['Produto atualizado com sucesso']})

@app.route('/api/shelflife/historico')
def shelflife_historico():
    return jsonify([
        {'created_at': '2026-09-06T10:00:00', 'usuario': 'admin@teste.com', 'acao': 'Promocao de Preco', 'obs_logistica': 'Quantidade atual: [120] → [150]', 'obs_gerais': 'Ajuste de estoque'}
    ])

# ============================================================
# API VALTER
# ============================================================

@app.route('/api/valter/chat', methods=['POST'])
def valter_chat():
    try:
        data = request.get_json(force=True)
        mensagem = data.get('mensagem', '')
        resposta = f"Olá! Recebi sua pergunta: '{mensagem}'. O sistema Átomo está funcionando com dados de exemplo. Em breve teremos dados reais integrados!"
        return jsonify({
            'resposta': resposta,
            'content': [{'type': 'text', 'text': resposta}]
        })
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

@app.route('/api/valter/alertas')
def valter_alertas():
    return jsonify({
        'alertas': [
            {'icone': '🚨', 'texto': '3 produtos vencem em 7 dias!', 'tipo': 'danger', 'pergunta': 'Liste os produtos que vencem em 7 dias'},
            {'icone': '⚠️', 'texto': '5 produtos críticos sem ação', 'tipo': 'warning', 'pergunta': 'Quais os produtos críticos sem ação?'}
        ]
    })

# ============================================================
# API EXPORTAR
# ============================================================

@app.route('/api/exportar', methods=['GET'])
def exportar_dados():
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Dados'
        
        # Cabeçalho
        ws['A1'] = 'KPI'
        ws['B1'] = 'Valor'
        ws['A1'].font = Font(bold=True)
        ws['B1'].font = Font(bold=True)
        
        # Dados
        ws['A2'] = 'Faturamento'
        ws['B2'] = 'R$ 1.250.000,00'
        ws['A3'] = 'Devoluções'
        ws['B3'] = 'R$ 85.000,00'
        ws['A4'] = 'Clientes'
        ws['B4'] = '342'
        
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
# API CACHE CLEAR
# ============================================================

@app.route('/api/cache/clear', methods=['GET', 'POST'])
def limpar_cache():
    return jsonify({"status": "cache limpo!"})

# ============================================================
# INICIALIZAÇÃO
# ============================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f"🚀 Servidor rodando em http://0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)
