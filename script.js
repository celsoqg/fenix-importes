// ==============================================
// ⚙️ CONFIGURAÇÕES — SUAS INFORMAÇÕES JÁ PREENCHIDAS!
// ==============================================
const CONFIG = {
  chavePix: "junioqg2@gmail.com",
  nomeRecebedor: "Fênix Importes",
  whatsapp: "5521990422420",
  freteFixo: 25.00,
  fretePorEstado: {
    SP: 25.00, RJ: 25.00, MG: 25.00, DF: 25.00, OUTROS: 25.00
  }
};

// ==============================================
// 🛒 CATÁLOGO DE PRODUTOS — PREÇOS DE REVENDA CONFIRMADOS!
// ==============================================
const produtos = [
  // === 💦 WATER BARIOSTATIC VIAL ===
  {
    id: 1,
    nome: "💦 WATER BARIOSTATIC VIAL 2ML",
    preco: 40.00,
    categoria: "perda-peso",
    imagem: "COLOQUE_LINK_DA_FOTO_AQUI",
    tag: "Disponível"
  },
  {
    id: 2,
    nome: "💦 WATER BARIOSTATIC VIAL 3ML",
    preco: 60.00,
    categoria: "perda-peso",
    imagem: "COLOQUE_LINK_DA_FOTO_AQUI",
    tag: "Disponível"
  },
  {
    id: 3,
    nome: "💦 WATER BARIOSTATIC VIAL 10ML",
    preco: 1000.00,
    categoria: "perda-peso",
    imagem: "COLOQUE_LINK_DA_FOTO_AQUI",
    tag: "Disponível"
  },

  // === ❤️ TIRZEPATIDA PY ===
  {
    id: 4,
    nome: "❤️ TIRZEDRAL 4X 15 MG",
    preco: 1000.00,
    categoria: "perda-peso",
    imagem: "COLOQUE_LINK_DA_FOTO_AQUI",
    tag: "Disponível"
  },
  {
    id: 5,
    nome: "❤️ T36 MD 15MG",
    preco: 1000.00,
    categoria: "perda-peso",
    imagem: "COLOQUE_LINK_DA_FOTO_AQUI",
    tag: "Disponível"
  },
  {
    id: 6,
    nome: "🟠 TG 15MG",
    preco: 1000.00,
    categoria: "perda-peso",
    imagem: "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAASABIAAD/4QBMRXhpZgAATU0AKgAAAAgAAYdpAAQAAAABAAAAGgAAAAAAA6ABAAMAAAABAAEAAKACAAQAAAABAAABBKADAAQAAAABAAAA0QAAAAD/7QA4UGhvdG9zaG9wIDMuMAA4QklNBAQAAAAAAAA4QklNBCUAAAAAABDUHYzZjwCyBOmACZjs+EJ+/8AAEQgA0QEEAwEiAAIRAQMRAf/EAB8AAAEFAQEBAQEBAAAAAAAAAAABAgMEBQYHCAkKC//EALUQAAIBAwMCBAMFBQQEAAABfQECAwAEEQUSITFBBhNRYQcicRQygZGhCCNCscEVUtHwJDNicoIJChYXGBkaJSYnKCkqNDU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6g4SFhoeIiYqSk5SVlpeYmZqio6Slpqeoqaqys7S1tre4ubrCw8TFxsfIycrS09TV1tfY2drh4uPk5ebn6Onq8fLz9PX29/j5+v/EAB8BAAMBAQEBAQEBAQEAAAAAAAABAgMEBQYHCAkKC//EALURAAIBAgQEAwQHBQQEAAECdwABAgMRBAUhMQYSQVEHYXETIjKBCBRCkaGxwQkjM1LwFWJy0QoWJDThJfEXGBkaJicoKSo1Njc4OTpDREVGR0hJSlNUVVZXWFlaY2RlZmdoaWpzdHV2d3h5eoKDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uLj5OXm5+jp6vLz9PX29/j5+v/bAEMAAgICAgICBAICBAUEBAQFBwUFBQUHCQcHBwcHCQsJCQkJCQkLCwsLCwsLCw0NDQ0NDQ8PDw8PEREREREREREREf/bAEMBAwMDBAQEBwQEBxIMCgwSEhISEhISEhISEhISEhISEhISEhISEhISEhISEhISEhISEhISEhISEhISEhISEhISEv/dAAQAEf/aAAwDAQACEQMRAD8A/fyiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooA//Q/fyiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi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4up2xr+Vnxi16Tw2dZvbd0juGuriO3LkAb9ztnkEbgqkqDwxAXqa/aLWNFufD0ghmbfDLkRS9MkDJUjs2ATjuOR0OPyR8V+D5fGninU9Bi06TU3a7uQIIomlkG5nQlQgLKcEjK4PPBr8z8Q6cY0sGnFyXO9FrfTY+p4erKVapUqaaK/3nj9zNpOr20avdXVxI0McskdqzDzI2aPLLjC4zwSnzY3AHdmnwaTe2Gmx23gu2gshuSQtchiWRj8ygMC4OAPvgYGFx/d+0/B/7I/xW15RJeW1vo0B2nddyDewxjiOPe2QB0fbX1B4R/Yw8B6UUn8XXt1q0i53Rp/o0DZ9VQtJx7SD6V8fgeGM6xatSw/JD++7L/wFWb+5ntYjPMHR05r+mv8AwD8s7PRbm8tTpmrSnUHmygAQJksAAFVecgjK4ORnrXufgP8AZb+JWsW8EGi6E2nW0SiOOa+/cBV/7aZlYHqSFOa/XTwv4B8F+CoRD4V0u1sfkCF4YwJHUf35Pvv9WJrrsCvrsD4bwt/woYlyX8sfdX/B+5Hh1+Jqj0owt6nwZ4T/AGI9PiKT+NtYkmIwWt7BAi8dvNk3Eg/7imvprwp8DfhX4NVW0fRrZpQoUz3C+fIcd90m7aT324/ICvWaK+zy7hvKsBb6rh0mur1f3u7PDr5hia/8Sbt26fcIABwKWiivcOMKKKKACiiigAooooAKKKKACiiigD//0v38ooooAKKKKACiiigAooooAKKKKACiiigAooooArXlnbX9s9ndqHjkG1lPHH1HIPoRyD0qtpejaRokBttHtobWNmLssKBAzHqxwBknuTya0qKVle4BRRRTAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigD/9P9/KKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigD/9T9/KKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigD/9k=",
    tag: "Disponível"
  },
  {
    id: 7,
    nome: "🟠 TG 5MG",
    preco: 420.00,
    categoria: "perda-peso",
    imagem: "COLOQUE_LINK_DA_FOTO_AQUI",
    tag: "Disponível"
  },
  {
    id: 8,
    nome: "🟡 TIRZEC MD 15MG",
    preco: 1000.00,
    categoria: "perda-peso",
    imagem: "COLOQUE_LINK_DA_FOTO_AQUI",
    tag: "Disponível"
  },
  {
    id: 9,
    nome: "🟡 TIRZEC 4x 15MG",
    preco: 1000.00,
    categoria: "perda-peso",
    imagem: "data:image/jpeg;base64,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",
    tag: "Disponível"
  },
  {
    id: 10,
    nome: "💜 LIPOLESS MD 15MG",
    preco: 1000.00,
    categoria: "perda-peso",
    imagem: "COLOQUE_LINK_DA_FOTO_AQUI",
    tag: "Disponível"
  },
  {
    id: 11,
    nome: "💜 LIPOLESS 4X 15MG",
    preco: 1000.00,
    categoria: "perda-peso",
    imagem: "https://mxeacxvjopeefvqrahby.supabase.co/storage/v1/object/public/produtos/prod-1788822939567-yk3mf4.jpg",
    tag: "Disponível"
  },
  {
    id: 12,
    nome: "⚫ LIPOLAND MD 15MG",
    preco: 1000.00,
    categoria: "perda-peso",
    imagem: "COLOQUE_LINK_DA_FOTO_AQUI",
    tag: "Disponível"
  },
  {
    id: 13,
    nome: "⚫ LIPOLAND 4X 15MG",
    preco: 1000.00,
    categoria: "perda-peso",
    imagem: "COLOQUE_LINK_DA_FOTO_AQUI",
    tag: "Disponível"
  },
  {
    id: 14,
    nome: "💙 SLIMEX MD 15MG",
    preco: 1000.00,
    categoria: "perda-peso",
    imagem: "COLOQUE_LINK_DA_FOTO_AQUI",
    tag: "Disponível"
  },
  {
    id: 15,
    nome: "🟤 GLUCONEX 4X 15MG",
    preco: 1000.00,
    categoria: "perda-peso",
    imagem: "COLOQUE_LINK_DA_FOTO_AQUI",
    tag: "Disponível"
  },
  {
    id: 16,
    nome: "🟤 GLUCONEX 4X SER 2.5MG 💉",
    preco: 457.00,
    categoria: "perda-peso",
    imagem: "COLOQUE_LINK_DA_FOTO_AQUI",
    tag: "Disponível"
  }
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
