const fs = require('fs');
const readline = require('readline');
const http = require('http');
const url = require('url');
const { google } = require('googleapis');
require('dotenv').config();

const TOKEN_PATH = 'token.json';
const CREDENTIALS_PATH = 'credentials.json';
const SCOPES = ['https://www.googleapis.com/auth/gmail.readonly'];

let oauth2Client;
let server;

function startServer(callback) {
  server = http.createServer(async (req, res) => {
    const queryUrl = url.parse(req.url, true);
    const code = queryUrl.query.code;

    if (code) {
      res.end('✅ Autorização concedida! Você pode fechar esta aba.');
      
      try {
        const { tokens } = await oauth2Client.getToken(code);
        oauth2Client.setCredentials(tokens);
        fs.writeFileSync(TOKEN_PATH, JSON.stringify(tokens));
        console.log('\n✅ Token salvo em token.json');
        server.close();
        callback();
      } catch (err) {
        console.error('❌ Erro ao obter token:', err);
        server.close();
      }
    } else {
      res.end('❌ Nenhum código de autorização recebido');
    }
  }).listen(3000, () => {
    console.log('✅ Servidor local iniciado na porta 3000');
  });
}

async function authenticate() {
  try {
    const content = fs.readFileSync(CREDENTIALS_PATH);
    const credentials = JSON.parse(content);
    const { client_id, client_secret, redirect_uris } = credentials.installed;

    oauth2Client = new google.auth.OAuth2(
      client_id,
      client_secret,
      redirect_uris[0]
    );

    // Se token já existe, usa ele
    if (fs.existsSync(TOKEN_PATH)) {
      const token = JSON.parse(fs.readFileSync(TOKEN_PATH));
      oauth2Client.setCredentials(token);
      console.log('✅ Token encontrado. Autenticação pronta!');
      return;
    }

    // Se não existe, gera novo
    const authUrl = oauth2Client.generateAuthUrl({
      access_type: 'offline',
      scope: SCOPES,
    });

    console.log('\n🔗 Abra este link no navegador:');
    console.log(authUrl);
    console.log('\n⏳ Aguardando autorização...\n');

    startServer(() => {
      console.log('✅ Autenticação concluída!');
      process.exit(0);
    });

  } catch (error) {
    console.error('❌ Erro:', error.message);
    process.exit(1);
  }
}

authenticate();