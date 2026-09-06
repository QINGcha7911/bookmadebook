/* ============================================================
 * OSS 签名下载模块测试（fc/oss.mjs）
 * 覆盖：key 规范 / V1 预签名 URL（固定输入回归锚点）/ env 注入器行为
 * 运行：npm test
 * ============================================================ */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { ossKeyOf, signUrl, buildSignDownloadUrl } from '../fc/oss.mjs';

const CFG = {
  bucket: 'bookmadebook-audio',
  region: 'cn-hongkong',
  accessKeyId: 'AKTEST123',
  secretAccessKey: 'SECRET456',
  key: 'orders/BM-TEST001.mp3',
};

describe('OSS 签名下载（fc/oss.mjs）', () => {
  test('ossKeyOf：orders/{order_id}.mp3 规范（与 daemon 上传一致）', () => {
    assert.equal(ossKeyOf('BM-ABC123'), 'orders/BM-ABC123.mp3');
    assert.equal(ossKeyOf('BM-ABC123').startsWith('orders/'), true);
  });

  test('signUrl：固定输入回归锚点（V1 签名 URL 结构完整）', () => {
    const url = signUrl({ ...CFG, now: 1750000000000, expiresInSec: 86400 });
    assert.equal(
      url,
      'https://bookmadebook-audio.cn-hongkong.aliyuncs.com/orders/BM-TEST001.mp3'
        + '?OSSAccessKeyId=AKTEST123&Expires=1750086400&Signature=UlQQbEtdt09vva%2B1idL80y52jd8%3D'
    );
  });

  test('signUrl：默认 24h 过期、可注入 now/expiresInSec', () => {
    const now = 1750000000000;
    const url = signUrl({ ...CFG, now });
    const expires = Number(new URL(url).searchParams.get('Expires'));
    assert.equal(expires, Math.floor(now / 1000) + 24 * 3600);
    const short = signUrl({ ...CFG, now, expiresInSec: 60 });
    assert.equal(Number(new URL(short).searchParams.get('Expires')), Math.floor(now / 1000) + 60);
  });

  test('buildSignDownloadUrl：环境变量齐全 → 行级签名函数', async () => {
    const env = {
      OSS_BUCKET: 'bookmadebook-audio',
      OSS_REGION: 'cn-hongkong',
      OSS_AK_ID: 'AKENV',
      OSS_AK_SECRET: 'SECENV',
    };
    const fn = buildSignDownloadUrl(env);
    assert.equal(typeof fn, 'function');
    const url = await fn({ id: 'BM-ENV1', status: 'done', oss_key: 'orders/BM-ENV1.mp3' });
    assert.match(url, /^https:\/\/bookmadebook-audio\.cn-hongkong\.aliyuncs\.com\/orders\/BM-ENV1\.mp3\?/);
    assert.ok(url.includes('OSSAccessKeyId=AKENV'));
    assert.ok(url.includes('Signature='));
    assert.ok(url.includes('Expires='));
  });

  test('buildSignDownloadUrl：兼容 ALIBABA_CLOUD_* 变量', () => {
    const fn = buildSignDownloadUrl({
      OSS_BUCKET: 'b', OSS_REGION: 'r',
      ALIBABA_CLOUD_ACCESS_KEY_ID: 'AK2', ALIBABA_CLOUD_ACCESS_KEY_SECRET: 'SK2',
    });
    assert.equal(typeof fn, 'function');
  });

  test('buildSignDownloadUrl：配置不全返回 null（无注入=占位链接回退）', () => {
    assert.equal(buildSignDownloadUrl({}), null);
    assert.equal(buildSignDownloadUrl({ OSS_BUCKET: 'b' }), null);
    assert.equal(buildSignDownloadUrl({ OSS_BUCKET: 'b', OSS_REGION: 'r', OSS_AK_ID: 'a' }), null);
  });

  test('签名器：无 oss_key 的 done 订单不签发（历史/未上传 → null）', async () => {
    const fn = buildSignDownloadUrl({
      OSS_BUCKET: 'bookmadebook-audio', OSS_REGION: 'cn-hongkong',
      OSS_AK_ID: 'a', OSS_AK_SECRET: 's',
    });
    assert.equal(await fn({ id: 'BM-OLD1', status: 'done', oss_key: null }), null);
    assert.equal(await fn({ id: 'BM-OLD2', status: 'done' }), null);
  });
});
