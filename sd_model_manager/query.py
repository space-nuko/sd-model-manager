import re
from typing import Optional, Pattern
from sqlalchemy import create_engine, func, select, not_, or_, and_, nulls_last, exists

from sd_model_manager.models.sd_models import SDModel, LoRAModel, LoRAModelSchema


class AbstractCriteria:
    re: Optional[Pattern]

    def apply(self, orm_query, query_string):
        if self.re is not None:
            matches = self.re.search(query_string)
            if matches is None:
                return orm_query, query_string
            query_string = re.sub(self.re, "", query_string).strip()
            return self.do_apply(orm_query, matches), query_string

        return self.do_apply(orm_query, query_string), query_string

    def do_apply(self, orm_query, matches):
        pass


class StringCriteria(AbstractCriteria):
    def __init__(self, prefix, column, exact=False):
        self.re = re.compile(rf'(^| +)(-)?{prefix}:("([^"]+)"|(\S+))', re.I)
        self.column = column
        self.exact = exact

    def do_apply(self, orm_query, matches):
        _not = matches[2]
        m = matches[4] or matches[3]
        if self.exact:
            stmt = func.lower(self.column) == m.lower()
        else:
            stmt = self.column.ilike(f"%{m}%")
        if _not:
            stmt = or_(self.column.is_(None), not_(stmt))
        return orm_query.where(stmt)


class NumberCriteria(AbstractCriteria):
    def __init__(self, prefix, column, type):
        self.re = re.compile(
            rf"(^| +)(-)?{prefix}:(==|!=|>|<|>=|<=)?(\d+(?:\.\d+)?)", re.I
        )
        self.column = column
        self.type = type

    def do_apply(self, orm_query, matches):
        _not = matches[2]
        op = matches[3] or "=="
        try:
            num = self.type(matches[4])
        except Exception:
            return orm_query
        if op == "!=":
            stmt = self.column != num
        elif op == ">":
            stmt = self.column > num
        elif op == "<":
            stmt = self.column < num
        elif op == ">=":
            stmt = self.column >= num
        elif op == "<=":
            stmt = self.column <= num
        else:
            stmt = self.column == num

        if _not:
            stmt = or_(self.column.is_(None), not_(stmt))
        else:
            stmt = and_(self.column.is_not(None), stmt)

        return orm_query.where(stmt)


class HasCriteria(AbstractCriteria):
    def __init__(self, suffix, column, compare="", count=False):
        self.re = re.compile(rf"(^| +)(-)?has:{suffix}", re.I)
        self.column = column
        self.compare = ""
        self.count = count

    def do_apply(self, orm_query, matches):
        no = matches[2] is not None
        if self.count:
            stmt = self.column.any()
        else:
            stmt = and_(self.column.is_not(None), self.column != self.compare)
        if no:
            stmt = not_(stmt)
        return orm_query.where(stmt)


class OrderByCriteria(AbstractCriteria):
    def __init__(self, suffix, column, reversed=None, default=""):
        self.re = re.compile(rf"(^| +)order(:reverse)?:{suffix}", re.I)
        self.column = column
        self.reversed = reversed or False
        if reversed is None:
            self.reversed = isinstance(default, (int, float))
        self.default = default

    def do_apply(self, orm_query, matches):
        reverse = matches[2] is not None
        if self.reversed:
            reverse = not reverse
        order = func.coalesce(self.column, self.default)
        if reverse:
            order = order.desc()
        return orm_query.order_by(order)


class BasicCriteria(AbstractCriteria):
    def __init__(self):
        self.re = None

    def do_apply(self, orm_query, query_string):
        for s in query_string.split(" "):
            s = s.strip()
            if s:
                orm_query = orm_query.where(
                    or_(
                        SDModel.display_name.ilike(f"%{s}%"),
                        SDModel.filepath.ilike(f"%{s}%"),
                    )
                )
        return orm_query


ALL_CRITERIA = [
    OrderByCriteria("id", SDModel.id),
    OrderByCriteria("root_path", SDModel.root_path),
    OrderByCriteria("filepath", SDModel.filepath),
    OrderByCriteria("filename", SDModel.filename),
    OrderByCriteria("name", SDModel.display_name),
    OrderByCriteria("version", SDModel.version),
    OrderByCriteria("author", SDModel.author),
    OrderByCriteria("source", SDModel.source),
    OrderByCriteria("keywords", SDModel.keywords),
    OrderByCriteria("negative_keywords", SDModel.negative_keywords),
    OrderByCriteria("description", SDModel.description),
    OrderByCriteria("tags", SDModel.tags),
    OrderByCriteria("rating", LoRAModel.rating, default=0),
    OrderByCriteria("notes", SDModel.notes),
    OrderByCriteria("network_dim", LoRAModel.network_dim),
    OrderByCriteria("dim", LoRAModel.network_dim),
    OrderByCriteria("network_alpha", LoRAModel.network_alpha),
    OrderByCriteria("alpha", LoRAModel.network_alpha),
    OrderByCriteria("resolution", LoRAModel.resolution_width, default=0),
    OrderByCriteria("unique_tags", LoRAModel.unique_tags, default=0),
    OrderByCriteria("keep_tokens", LoRAModel.keep_tokens, default=0),
    OrderByCriteria("noise_offset", LoRAModel.noise_offset, default=0.0),
    StringCriteria("root_path", SDModel.root_path),
    StringCriteria("filepath", SDModel.filepath),
    StringCriteria("filename", SDModel.filename),
    StringCriteria("name", SDModel.display_name),
    StringCriteria("author", SDModel.author),
    StringCriteria("source", SDModel.source),
    StringCriteria("keywords", SDModel.keywords),
    StringCriteria("description", SDModel.description),
    StringCriteria("tags", SDModel.tags),
    StringCriteria("tag", SDModel.tags),
    StringCriteria("notes", SDModel.notes),
    StringCriteria("network_module", LoRAModel.network_module, exact=True),
    StringCriteria("module_name", LoRAModel.module_name, exact=True),
    StringCriteria("module", LoRAModel.module_name, exact=True),
    StringCriteria("network_dim", LoRAModel.network_dim, exact=True),
    StringCriteria("dim", LoRAModel.network_dim, exact=True),
    StringCriteria("network_alpha", LoRAModel.network_alpha, exact=True),
    StringCriteria("alpha", LoRAModel.network_alpha, exact=True),
    StringCriteria("model_hash", LoRAModel.model_hash, exact=True),
    StringCriteria("hash", LoRAModel.model_hash, exact=True),
    StringCriteria("legacy_hash", LoRAModel.legacy_hash, exact=True),
    NumberCriteria("id", SDModel.id, int),
    NumberCriteria("rating", SDModel.rating, int),
    NumberCriteria("unique_tags", LoRAModel.unique_tags, int),
    NumberCriteria("num_epochs", LoRAModel.num_epochs, int),
    NumberCriteria("epochs", LoRAModel.num_epochs, int),
    NumberCriteria("epoch", LoRAModel.epoch, int),
    NumberCriteria("session_id", LoRAModel.session_id, int),
    NumberCriteria("resolution", LoRAModel.resolution_width, int),
    NumberCriteria("keep_tokens", LoRAModel.keep_tokens, int),
    NumberCriteria("learning_rate", LoRAModel.learning_rate, float),
    NumberCriteria("lr", LoRAModel.learning_rate, float),
    NumberCriteria("text_encoder_lr", LoRAModel.text_encoder_lr, float),
    NumberCriteria("tenc_lr", LoRAModel.text_encoder_lr, float),
    NumberCriteria("unet_lr", LoRAModel.unet_lr, float),
    NumberCriteria("noise_offset", LoRAModel.noise_offset, float),
    HasCriteria("name", SDModel.display_name),
    HasCriteria("version", SDModel.version),
    HasCriteria("author", SDModel.author),
    HasCriteria("source", SDModel.source),
    HasCriteria("keywords", SDModel.keywords),
    HasCriteria("negative_keywords", SDModel.negative_keywords),
    HasCriteria("description", SDModel.description),
    HasCriteria("tags", SDModel.tags),
    HasCriteria("rating", SDModel.rating, 0),
    HasCriteria("image", SDModel.preview_images, 0, count=True),
    HasCriteria("preview_image", SDModel.preview_images, 0, count=True),
    HasCriteria("vae", LoRAModel.vae_hash),
    HasCriteria("tag_frequency", LoRAModel.unique_tags),
    HasCriteria("dataset_dirs", LoRAModel.dataset_dirs),
    HasCriteria("reg_dataset_dirs", LoRAModel.reg_dataset_dirs),
    HasCriteria("network_args", LoRAModel.network_args),
    HasCriteria("noise_offset", LoRAModel.noise_offset, 0),
    HasCriteria("keep_tokens", LoRAModel.keep_tokens.is_not(None), 0),
    BasicCriteria(),
]


def build_search_query(orm_query, query_string):
    for criteria in ALL_CRITERIA:
        orm_query, query_string = criteria.apply(orm_query, query_string)

    return orm_query
