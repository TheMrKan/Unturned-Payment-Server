using Newtonsoft.Json;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;

namespace DotNetModule
{
    public class FormdataSender
    {
        /// <summary>
        /// Отправляет запросы в формате multipart/form-data для Lava API
        /// </summary>
        /// <param name="url">URL, на который будет отправлен запрос</param>
        /// <param name="method">'POST' или 'GET'</param>
        /// <param name="headers">Заголовки, которые будут добавлены к запросу</param>
        /// <param name="fields">StringContent поля, которые будут добавлены в FormData.</param>
        /// <returns>Ответ в формате JSON, полученный от API</returns>
        public async static Task<string> SendAsync(string url, string method, Dictionary<String, String> headers, Dictionary<String, String> fields)
        {
            HttpClient httpClient = new HttpClient();
            HttpMethod httpMethod = null;
            if (method == "POST") httpMethod = HttpMethod.Post;
            else httpMethod = HttpMethod.Get;
            HttpRequestMessage msg = new HttpRequestMessage(httpMethod, url);

            foreach (var kvp in headers)
            {
                msg.Headers.Add(kvp.Key, kvp.Value);
            }

            
            MultipartFormDataContent form = new MultipartFormDataContent();
            foreach (var kvp in fields)
            {
                form.Add(new StringContent(kvp.Value), kvp.Key);
            }
            
            msg.Content = form;
            var response = await httpClient.SendAsync(msg);
            httpClient.Dispose();

            return await response.Content.ReadAsStringAsync();
        }

        /// <summary>
        /// Точка входа для Python. Вызывает асинхронный вариант функции. 
        /// </summary>
        /// <param name="url">URL, на который будет отправлен запрос</param>
        /// <param name="method">'POST' или 'GET'</param>
        /// <param name="headers">Заголовки, которые будут добавлены к запросу</param>
        /// <param name="fields">StringContent поля, которые будут добавлены в FormData.</param>
        /// <returns>Ответ в формате JSON, полученный от API</returns>
        public static string Send(string url, string method, Dictionary<string, string> headers, Dictionary<string, string> fields)
        {
            return Task.Run(async () => { return await SendAsync(url, method, headers, fields); }).Result;
        }
    }
}
