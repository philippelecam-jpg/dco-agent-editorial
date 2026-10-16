import test from 'node:test';
import assert from 'node:assert/strict';
import worker from '../src/index.js';

test('access email keeps the verified address and includes the same one-time link in HTML and text', async () => {
  const originalFetch = globalThis.fetch;
  let mail;
  globalThis.fetch = async (url, options) => {
    assert.equal(url, 'https://api.resend.com/emails');
    mail = JSON.parse(options.body);
    return Response.json({id:'test-email'});
  };
  const env = {
    EMAIL_FROM:'Rachel Entreprises <rachel@decisionsandco.com>',
    RESEND_API_KEY:'test', PUBLIC_BASE_URL:'https://fabrik.test',
    DB:{prepare(){return {bind(){return this;},async run(){return {};},async first(){return {id:'lead'};}};}}
  };
  try {
    const response = await worker.fetch(new Request('https://fabrik.test/api/signup', {
      method:'POST', headers:{'content-type':'application/json'},
      body:JSON.stringify({email:'client@example.com',name:'Jean <Client>',company:'Entreprise',site:'https://example.com'})
    }),env);
    assert.equal(response.status,200);
    assert.equal(mail.from,'La Fabrik — Décisions & Co <rachel@decisionsandco.com>');
    assert.equal(mail.to,'client@example.com');
    assert.equal(mail.subject,'Votre lien d’accès à La Fabrik');
    assert.match(mail.html,/Jean &lt;Client&gt;/);
    assert.match(mail.text,/15 minutes/);
    assert.match(mail.text,/le plus récent/);
    const link = mail.text.split('\n').find(line=>line.startsWith('https://fabrik.test/verify?'));
    assert(link);
    assert.match(new URL(link).searchParams.get('token'),/.+/);
    assert(mail.html.includes(link.replaceAll('&','&amp;')));
  } finally {globalThis.fetch=originalFetch;}
});
