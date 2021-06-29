from io import StringIO
from urllib.parse import urlparse
import requests
import csv


def is_queue_file_valid_by_url(url):
    """
        Columns:
            - Title
            - Author
            - File ID
            - Date Time on Air
            - On Air always
    :param url:
    :return:
    """
    url = urlparse(url)
    url = url._replace(fragment='')
    path_list = url.path.split('/')
    if path_list[-1] is 'edit':
        del path_list[-1]
    path_list.append('export')
    url = url._replace(query='format=csv')
    url = url._replace(path='/'.join(path_list))

    url = url.geturl()

    response = requests.get(url=url, )
    file = StringIO(response.content.decode('utf-8'))

    reader = csv.reader(file)

    for row in reader:
        title = row[0]
        author = row[1]
        file_id = row[2]
        date_time_on_air = row[3]
        on_air_always = row[4]

        if title and author and file_id and date_time_on_air and on_air_always:
            return True
        return False
