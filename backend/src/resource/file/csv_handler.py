import pandas as pd
from pandas import DataFrame


class CSVHandler:
    def __init__(self):
        self.df = None

    @staticmethod
    def read(path):
        """

        :param path:
        :return:
        """
        return pd.read_csv(path)

    @staticmethod
    def write(data: DataFrame, path: str):
        data.to_csv(path, index=False)


