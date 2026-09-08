// ==============================================
// ⚙️ 👇 PREENCHA TUDO AQUI ABAIXO 👇
// ==============================================
const CONFIG = {
  chavePix: "junioqg2@gmail.com",      // ← EX: seuemail@gmail.com ou CPF ou telefone
  nomeRecebedor: "Fênix Importes",             // ← Pode deixar assim
  whatsapp: "+5521990422420",                   // ← Seu WhatsApp com DDD e código do país (sem espaços nem símbolos)
  freteFixo: 12.50,                            // ← Valor do frete padrão (use PONTO, não vírgula)
  fretePorEstado: {                            // ← Ajuste os valores como quiser
    SP: 10.00, RJ: 12.50, MG: 13.00, DF: 15.00, OUTROS: 18.00
  }
};

// ==============================================
// 📦 👇 SEUS PRODUTOS — EDITE COMO QUISER 👇
// ==============================================
const produtos = [
  // EXEMPLO 1 — você pode apagar e colocar os seus
  { id: 1, nome: "ACNECUR ISOTRETINOÍNA 20MG", preco: 195.00, categoria: "estetica-pele", imagem: "https://via.placeholder.com/300x250/ffffff/000000?text=ACNECUR", tag: "Sob encomenda" },
  { id: 2, nome: "Alluvi GHK-CU 50mg", preco: 727.00, categoria: "hormonios", imagem: "https://via.placeholder.com/300x250/ffffff/000000?text=GHK-CU", tag: "Sob encomenda" },
  { id: 3, nome: "ALLUVI GLOW GHK-CU 50MG", preco: 384.00, categoria: "hormonios", imagem: "https://via.placeholder.com/300x250/ffffff/000000?text=GLOW+GHK-CU", tag: "Sob encomenda" },
  { id: 4, nome: "ALPHA Alphabol 10mg 50COMP", preco: 190.00, categoria: "performance", imagem: "https://via.placeholder.com/300x250/ffffff/000000?text=ALPHABOL", tag: "Sob encomenda" },
  { id: 5, nome: "ALPHA HGH-FRAG 10mg", preco: 353.00, categoria: "hormonios", imagem: "https://via.placeholder.com/300x250/ffffff/000000?text=HGH-FRAG", tag: "Sob encomenda" },
  { id: 6, nome: "Alpha Lab AOD 10mg", preco: 415.00, categoria: "perda-peso", imagem: "https://via.placeholder.com/300x250/ffffff/000000?text=AOD-9604", tag: "Sob encomenda" }
  // ← ADICIONE MAIS PRODUTOS AQUI, SEGUINDO O MESMO MODELO:
  // , { id: 7, nome: "NOME DO PRODUTO", preco: 99.99, categoria: "categoria", imagem: "LINK DA FOTO", tag: "Sob encomenda" }
];

// ==============================================
// 🛒 NÃO PRECISA MEXER DAQUI PARA BAIXO 🛒
// ==============================================
let carrinho = [];
let valorFrete = 0;
let estadoSelecionado = "";

document.addEventListener("DOMContentLoaded", () => {
  renderizarProdutos(produtos);
});

function renderizarProdutos(lista) {
  const grid = document.getElementById("produtos-grid");
  grid.innerHTML = lista.map(p => `
    <div class="produto-card">
      <div class="produto-img-wrap">
        ${p.tag ? `<span class="produto-tag">${p.tag}</span>` : ''}
        <img src="${p.imagem}" alt="${p.nome}" class="produto-img">
      </div>
      <div class="produto-info">
        <h3 class="produto-nome">${p.nome}</h3>
        <p class="produto-preco">R$ ${p.preco.toFixed(2).replace('.', ',')}</p>
        <button class="produto-btn" onclick="adicionarAoCarrinho(${p.id})">
          <i class="fas fa-shopping-cart"></i> Encomendar
        </button>
      </div>
    </div>
  `).join("");
}

function filtrarCategoria(cat) {
  document.querySelectorAll(".categoria-item").forEach(el => {
    el.classList.remove("active");
    if (el.dataset.cat === cat) el.classList.add("active");
  });
  const filtrados = cat === "todos" ? produtos : produtos.filter(p => p.categoria === cat);
  renderizarProdutos(filtrados);
}

function adicionarAoCarrinho(id) {
  const prod = produtos.find(p => p.id === id);
  carrinho.push({ ...prod });
  atualizarContadorCarrinho();
  alert(`✅ ${prod.nome} adicionado ao carrinho!`);
}

function removerDoCarrinho(index) {
  carrinho.splice(index, 1);
  atualizarContadorCarrinho();
  renderizarCarrinho();
  atualizarResumo();
}

function atualizarContadorCarrinho() {
  document.getElementById("cart-count").textContent = carrinho.length;
}

function abrirCarrinho() {
  if (carrinho.length === 0) {
    alert("Seu carrinho está vazio!");
    return;
  }
  renderizarCarrinho();
  document.getElementById("modal-carrinho").classList.remove("oculto");
}

function fecharCarrinho() {
  document.getElementById("modal-carrinho").classList.add("oculto");
}

function renderizarCarrinho() {
  const container = document.getElementById("carrinho-itens");
  container.innerHTML = carrinho.map((item, i) => `
    <div class="carrinho-item">
      <span>${item.nome}</span>
      <div>
        <span>R$ ${item.preco.toFixed(2).replace('.', ',')}</span>
        <button onclick="removerDoCarrinho(${i})"> ✕</button>
      </div>
    </div>
  `).join("");
  const subtotal = carrinho.reduce((s, i) => s + i.preco, 0);
  document.getElementById("carrinho-subtotal").textContent = subtotal.toFixed(2).replace('.', ',');
  document.getElementById("carrinho-total-valor").textContent = (subtotal + valorFrete).toFixed(2).replace('.', ',');
}

function calcularFreteCarrinho() {
  const cep = document.getElementById("cep-frete").value.replace(/\D/g, "");
  if (cep.length === 8) {
    valorFrete = CONFIG.freteFixo;
    document.getElementById("frete-valor").textContent = `Frete: R$ ${valorFrete.toFixed(2).replace('.', ',')}`;
    renderizarCarrinho();
  }
}

function abrirFormulario() {
  fecharCarrinho();
  estadoSelecionado = document.getElementById("estado").value;
  calcularFretePorEstado();
  atualizarResumo();
  document.getElementById("modal-finalizar").classList.remove("oculto");
}

function fecharModal() {
  document.getElementById("modal-finalizar").classList.add("oculto");
  document.getElementById("passo-dados").classList.remove("oculto");
  document.getElementById("passo-pagamento").classList.add("oculto");
}

function buscarCep() {
  const cep = document.getElementById("cep").value.replace(/\D/g, "");
  if (cep.length === 8) alert("✅ CEP encontrado! Preencha os demais dados.");
}

function calcularFretePorEstado() {
  estadoSelecionado = document.getElementById("estado").value;
  valorFrete = CONFIG.fretePorEstado[estadoSelecionado] || CONFIG.fretePorEstado.OUTROS;
}

function atualizarResumo() {
  const subtotal = carrinho.reduce((s, i) => s + i.preco, 0);
  const total = subtotal + valorFrete;
  document.getElementById("resumo-produtos").textContent = `R$ ${subtotal.toFixed(2).replace('.', ',')}`;
  document.getElementById("resumo-frete").textContent = `R$ ${valorFrete.toFixed(2).replace('.', ',')}`;
  document.getElementById("resumo-total").textContent = `R$ ${total.toFixed(2).replace('.', ',')}`;
  document.getElementById("valor-pix").textContent = total.toFixed(2).replace('.', ',');
  document.getElementById("chave-pix-exibicao").textContent = CONFIG.chavePix;
  gerarCodigoPix(total);
  atualizarLinkWhatsApp(total);
}

function irParaPagamento() {
  const campos = ["nome", "cpf", "celular", "email", "cep", "estado", "cidade", "bairro", "endereco", "numero", "termos"];
  for (const id of campos) {
    const el = document.getElementById(id);
    if (!el.value || (el.type === "checkbox" && !el.checked)) {
      alert("⚠️ Preencha todos os campos obrigatórios!");
      el.focus();
      return;
    }
  }
  calcularFretePorEstado();
  atualizarResumo();
  document.getElementById("passo-dados").classList.add("oculto");
  document.getElementById("passo-pagamento").classList.remove("oculto");
  document.querySelector(".passo").textContent = "2 de 2 - Pagamento";
}

function voltarParaDados() {
  document.getElementById("passo-pagamento").classList.add("oculto");
  document.getElementById("passo-dados").classList.remove("oculto");
  document.querySelector(".passo").textContent = "1 de 2 - Dados";
}

function gerarCodigoPix(valorTotal) {
  const codigoSimulado = `${CONFIG.chavePix}|valor:${valorTotal.toFixed(2)}|nome:${CONFIG.nomeRecebedor}`;
  document.getElementById("codigo-pix").value = codigoSimulado;
}

function copiarCodigoPix() {
  const input = document.getElementById("codigo-pix");
  input.select();
  document.execCommand("copy");
  alert("✅ Código copiado! Abra o app do seu banco e cole.");
}

function atualizarLinkWhatsApp(valorTotal) {
  const texto = `🛒 PEDIDO - Fênix Importes\n\nProdutos:\n${carrinho.map(i => `- ${i.nome}: R$ ${i.preco.toFixed(2)}`).join("\n")}\n\nFrete: R$ ${valorFrete.toFixed(2)}\nTOTAL: R$ ${valorTotal.toFixed(2).replace('.', ',')}\n\nDados:\nNome: ${document.getElementById("nome").value}\nCPF: ${document.getElementById("cpf").value}\nEndereço: ${document.getElementById("endereco").value}, ${document.getElementById("numero").value} - ${document.getElementById("bairro").value}/${document.getElementById("cidade").value}-${document.getElementById("estado").value}\n\n✅ Paguei via Pix! Segue comprovante 👇`;
  document.getElementById("link-whatsapp").href = `https://wa.me/${CONFIG.whatsapp}?text=${encodeURIComponent(texto)}`;
}
